"""Build train/dataset.json.gz (training pairs) from data/cards.json.gz + train/tags.jsonl.gz.

Run from repo root: uv run --project train python -m train.dataset

The unit of training is an **ability**, not a face: nothing at serve time embeds a face (vectors are per ability
`text_hash`, retrieval probes per ability, rerank is a Chamfer mean over ability sets), so every positive,
negative and self-pair is one ability's normalized text.

Output: {"pairs": [[anchor, positive], ...], "triplets": [[anchor, positive, hard_negative], ...], "stats": {...}}.
"""

import argparse
import gzip
import json
import math
import random
import re
from collections import Counter, defaultdict
from collections.abc import Hashable, Mapping, Sequence
from pathlib import Path

from app.text import build_face_abilities
from train.tags import TAGS_PATH, is_held_out_tag, load_tags

FaceId = tuple[str, int]
AbilityId = tuple[str, int, int]

# --- Tag attribution -------------------------------------------------------------------------------------------
# Scryfall tags live on cards; similarity is computed over abilities, two layers below. Pairing `mana dork` with the
# whole of Birds of Paradise teaches the model it means "Flying" as much as the mana ability.
#
# The signal is **within-tag token lift**: pool the tokens of every ability of every member of tag T and compare
# against the global ability distribution. What recurs across the members, relative to how common it is
# corpus-wide, *is* the concept. It is deliberately model-free: embedding similarity would ask the model which
# ability it already believes matches, and `mana dork` was broken in exactly that way. Lexical overlap with the tag
# name was also rejected: 71% of tags have no description and `morbid` shares no token with its ability.
#
# Precision over recall: a wrong attribution teaches a lie; a dropped one costs data we have in surplus.

# Calibrated on 120 hand-labelled attributions, stratified by margin band: precision ~55% in 0.2-0.3, ~64% in
# 0.3-0.5, ~86% in 0.5-0.8, ~88% above 0.8. The knee is at 0.5.
MIN_MARGIN = 0.5
# Tags no ability can justify (`alliteration`, `type addition human`) are properties of the name or type line.
# Their members share incidental token statistics, so no per-attribution threshold removes them; what separates
# them is that they resolve almost none of their members (`alliteration` 2% vs `morbid` 77%). Below this the tag is
# dropped whole, single-ability members included.
MIN_RESOLUTION_RATE = 0.5
# Below this many multi-ability members the resolution rate is too noisy to judge a tag by.
_MIN_RATE_SAMPLE = 8
# Below this a tag's token distribution is noise. Gates only multi-ability attribution: a single-ability member
# needs no evidence.
MIN_MEMBERS = 20
# A token on fewer abilities than this corpus-wide is a proper noun from one card ("rasputin", "powerstone").
_MIN_GLOBAL_DF = 25
_MIN_LOCAL_COUNT = 3
# Mildly negative so off-concept text is penalised rather than merely ignored.
_UNKNOWN_TOKEN_LIFT = -0.5
# A described tag's own words are direct evidence; this floors their lift.
_ANCHOR_TOKEN_LIFT = 1.5

_TOKEN = re.compile(r"[a-z0-9']+")
# True function words only. Domain words ("mana", "creature") are kept: lift already divides by global frequency,
# and "mana" is exactly the token that identifies a mana dork.
_STOPWORDS = frozenset(
    """a an the of to and or is are was be been it its this that these those them they he she his her you your my
    our their as at by for from in into on onto with without than then so if but not no nor do does did have has
    had will would can could may might must shall should there here who whom which what when where why how all any
    both each few more most other some such only own same too very""".split()  # noqa: SIM905
)


def _tokenize(text: str) -> frozenset[str]:
    """Content tokens, falling back to every token when that leaves nothing ("End the turn." would otherwise be
    unscoreable, and a sentinel score for it fabricated +100 margins)."""
    raw = _TOKEN.findall(text.lower())
    return frozenset({t for t in raw if t not in _STOPWORDS and len(t) > 1} or raw)


def _score(tokens: frozenset[str], lift: Mapping[str, float]) -> float:
    if not tokens:
        return _UNKNOWN_TOKEN_LIFT
    return sum(lift.get(t, _UNKNOWN_TOKEN_LIFT) for t in tokens) / len(tokens)


def attribute_tags(
    ability_texts: Mapping[AbilityId, str],
    tag_members: Mapping[str, Sequence[FaceId]],
    tag_descriptions: Mapping[str, str | None],
    min_margin: float = MIN_MARGIN,
) -> dict[str, list[AbilityId]]:
    """Map each tag to one ability per member face, or none for a face whose abilities the evidence does not
    separate. Single-ability faces are attributed unconditionally."""
    face_abilities: dict[FaceId, list[tuple[AbilityId, frozenset[str]]]] = defaultdict(list)
    global_df: Counter[str] = Counter()
    for key, text in ability_texts.items():
        tokens = _tokenize(text)
        face_abilities[(key[0], key[1])].append((key, tokens))
        global_df.update(tokens)
    total = len(ability_texts)

    attributed: dict[str, list[AbilityId]] = {}
    for tag, members in tag_members.items():
        faces = [f for f in members if f in face_abilities]
        singles = [face_abilities[f][0][0] for f in faces if len(face_abilities[f]) == 1]
        multis = [f for f in faces if len(face_abilities[f]) > 1]
        picks = list(singles)
        ran = bool(multis) and len(faces) >= MIN_MEMBERS
        if ran:
            lift = _lift_map(faces, face_abilities, global_df, total)
            for token in _tokenize(f"{tag.replace('-', ' ')} {tag_descriptions.get(tag) or ''}"):
                if global_df[token] >= _MIN_GLOBAL_DF:
                    lift[token] = max(lift.get(token, 0.0), _ANCHOR_TOKEN_LIFT)
            for face in multis:
                best, second = sorted(face_abilities[face], key=lambda e: _score(e[1], lift), reverse=True)[:2]
                if _score(best[1], lift) - _score(second[1], lift) >= min_margin:
                    picks.append(best[0])
        # Only a tag whose attribution ran can be judged by its resolution rate: a tag below MIN_MEMBERS was never
        # evaluated, and condemning it would throw away single-ability members that need no evidence.
        resolved = len(picks) - len(singles)
        if ran and len(multis) >= _MIN_RATE_SAMPLE and resolved / len(multis) < MIN_RESOLUTION_RATE:
            picks = []
        attributed[tag] = picks
    return attributed


def _lift_map(faces, face_abilities, global_df: Mapping[str, int], total: int) -> dict[str, float]:
    local_df: Counter[str] = Counter()
    local_total = 0
    for face in faces:
        for _, tokens in face_abilities[face]:
            local_df.update(tokens)
            local_total += 1
    return {
        t: math.log((n / local_total) / (global_df[t] / total))
        for t, n in local_df.items()
        if n >= _MIN_LOCAL_COUNT and global_df.get(t, 0) >= _MIN_GLOBAL_DF
    }


# --- Hard negatives --------------------------------------------------------------------------------------------
# MultipleNegativesRankingLoss otherwise sees only the other in-batch examples as negatives (31 random abilities at
# batch 32), so nothing teaches where a concept STOPS. Abilities from tags that co-occur with T sit on its boundary:
# for `mana dork` they are the mana abilities of lands.
_HARD_NEGATIVE_CO_TAGS = 12
_HARD_NEGATIVE_POOL_CAP = 2000
_HARD_NEGATIVE_MEMBER_SAMPLE = 200
_HARD_NEGATIVE_MIN_OVERLAP = 3


def hard_negative_pools[Id: Hashable](tag_to_ids: Mapping[str, Sequence[Id]]) -> dict[str, list[Id]]:
    """Per tag, members of strongly associated tags that are not members of the tag itself."""
    id_to_tags: dict[Id, set[str]] = defaultdict(set)
    for tag, ids in tag_to_ids.items():
        for i in ids:
            id_to_tags[i].add(tag)

    pools: dict[str, list[Id]] = {}
    for tag, ids in tag_to_ids.items():
        members = set(ids)
        co: Counter[str] = Counter()
        for i in list(ids)[:_HARD_NEGATIVE_MEMBER_SAMPLE]:
            co.update(other for other in id_to_tags[i] if other != tag)
        # Rank by *association* (overlap / other tag's size), not raw overlap: generic tags like `activated ability`
        # (8.8k cards) co-occur with everything and would make the pool huge and unfocused.
        ranked = sorted(
            ((n / len(tag_to_ids[other]), other) for other, n in co.items() if n >= _HARD_NEGATIVE_MIN_OVERLAP),
            reverse=True,
        )
        pool: dict[Id, None] = {}
        for _, other in ranked[:_HARD_NEGATIVE_CO_TAGS]:
            for i in tag_to_ids[other]:
                if i not in members:
                    pool[i] = None
        pools[tag] = list(pool)[:_HARD_NEGATIVE_POOL_CAP]
    return pools


# --- Examples --------------------------------------------------------------------------------------------------
_MAX_TAG_PAIRS_PER_TAG = 150
# Each anchor gets the full budget rather than a share: splitting starved the bare name (the form users type) and
# the model stopped ranking mana dorks for "mana dork".
_MAX_ANCHOR_PAIRS_PER_TAG = 600


def tag_anchors(tag: str, description: str | None) -> list[str]:
    """The bare name is what a player types ("mana dork"); name + description carries the meaning for opaque names.
    Training only on the descriptive form left the typed query unclaimed."""
    name = tag.replace("-", " ").replace("_", " ").strip()
    described = f"{name}. {description}".strip() if description else name
    return [a for a in dict.fromkeys([name, described]) if a]


def _distinct_by_text(ids: Sequence[AbilityId], texts: Mapping[AbilityId, str]) -> list[AbilityId]:
    """One id per distinct text: 63k ability rows collapse to ~37k texts and `Flying.` alone is 3,235 of them, so
    without this a keyword tag spends its whole budget on one string."""
    seen: dict[str, AbilityId] = {}
    for i in ids:
        seen.setdefault(texts[i], i)
    return list(seen.values())


def build_examples(
    texts: dict[AbilityId, str],
    tag_to_ids: dict[str, list[AbilityId]],
    descriptions: Mapping[str, str | None],
    rng: random.Random,
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    # Self-pairs (SimCSE): dropout noise is the only difference, which keeps every ability's embedding anchored.
    pairs = [(t, t) for t in dict.fromkeys(texts.values())]

    for ids in tag_to_ids.values():
        distinct = _distinct_by_text(ids, texts)
        rng.shuffle(distinct)
        for left, right in list(zip(distinct[::2], distinct[1::2]))[:_MAX_TAG_PAIRS_PER_TAG]:
            if left[0] != right[0]:
                pairs.append((texts[left], texts[right]))

    triplets = []
    pools = hard_negative_pools(tag_to_ids)
    for tag, ids in tag_to_ids.items():
        usable = _distinct_by_text(ids, texts)
        tag_texts = {texts[i] for i in usable}
        # v2 only checked a negative against its own positive; the same text also appears on other members, and a
        # negative equal to any of the tag's positives teaches the model to push the concept away from itself.
        pool = [texts[i] for i in pools[tag] if texts[i] not in tag_texts]
        for anchor in tag_anchors(tag, descriptions.get(tag)):
            for i in rng.sample(usable, min(len(usable), _MAX_ANCHOR_PAIRS_PER_TAG)):
                if pool:
                    triplets.append((anchor, texts[i], rng.choice(pool)))
                else:
                    pairs.append((anchor, texts[i]))
    return pairs, triplets


def load_ability_texts(cards: list[dict]) -> dict[AbilityId, str]:
    """(oracle_id, face_ix, ability_ix) -> normalized text, recomputed exactly as app/build.py does."""
    texts = {}
    for card in cards:
        for face in card["faces"]:
            abilities = build_face_abilities(
                oracle_text=face["oracle_text"], card_name=face["name"] or "", type_line=face["type_line"] or ""
            )
            # Training text must be the text whose vector is served; a drift in app.text since the build fails here.
            assert [a.text_hash for a in abilities] == face["_hashes"], f"{card['oracle_id']}: rebuild data/"
            for a in abilities:
                texts[(card["oracle_id"], face["face_ix"], a.ability_ix)] = a.normalized_text
    return texts


def load_cards(path: Path) -> list[dict]:
    return json.loads(gzip.decompress(path.read_bytes()))["cards"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", type=Path, default=Path("data/cards.json.gz"))
    parser.add_argument("--tags", type=Path, default=TAGS_PATH)
    parser.add_argument("--out", type=Path, default=Path("train/dataset.json.gz"))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    texts = load_ability_texts(load_cards(args.cards))
    faces_of: dict[str, list[FaceId]] = defaultdict(list)
    for oracle_id, face_ix, ability_ix in texts:
        if ability_ix == 0:
            faces_of[oracle_id].append((oracle_id, face_ix))

    # Held-out tags are the eval set (train/eval.py); training on them would score memorisation.
    tags = {t: v for t, v in load_tags(args.tags).items() if not is_held_out_tag(t)}
    descriptions = {t: desc for t, (desc, _) in tags.items()}
    members = {t: [f for oid in oids for f in faces_of.get(oid, ())] for t, (_, oids) in tags.items()}
    tag_to_ids = {t: ids for t, ids in attribute_tags(texts, members, descriptions).items() if ids}

    pairs, triplets = build_examples(texts, tag_to_ids, descriptions, random.Random(args.seed))
    stats = {"abilities": len(texts), "train_tags": len(tags), "attributed_tags": len(tag_to_ids),
             "pairs": len(pairs), "triplets": len(triplets)}
    payload = {"pairs": pairs, "triplets": triplets, "stats": stats}
    args.out.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False).encode(), mtime=0))
    print(f"wrote {args.out}: {stats}")


if __name__ == "__main__":
    main()
