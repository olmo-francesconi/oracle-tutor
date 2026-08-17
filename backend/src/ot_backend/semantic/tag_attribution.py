"""Attribute a card-level tag to the ability that actually justifies it.

Scryfall tags live on cards; similarity is computed over abilities, two layers
below. Pairing a tag with the whole face teaches the model that `mana dork`
means "Flying" as much as it means "tap this creature: Add one mana of any
color", because Birds of Paradise carries both.

The signal is **within-tag token lift**: pool the tokens of every ability of
every member of tag T and compare against the global ability distribution. What
recurs across the members, relative to how common it is corpus-wide, *is* the
concept. The tag's own membership defines it, so no model is consulted and the
attribution cannot inherit the retrieval model's existing mistakes — which
matters, because `mana dork` is broken in exactly that way today.

Two alternatives were rejected:

* **Embedding similarity to the current model** — circular. It asks the model
  which ability it already believes matches.
* **Lexical overlap with the tag name/description** — 71% of card tags have no
  description, and a slug like `morbid` shares no token with "if a creature
  died this turn". It would silently drop most tags.

The gate is a margin between the best and second-best ability, and the rule is
**precision over recall: drop when unsure**. A wrong attribution teaches a lie;
a dropped one costs data we have in surplus. On the live corpus a margin of 0.3
resolves 71.6% of the taggings that need attribution, while cutting
`alliteration` — a property of the card *name*, groundable in no ability — from
2,763 members to 329.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

logger = logging.getLogger("ot_backend.semantic.tag_attribution")

FaceIdentity = tuple[str, int]
AbilityIdentity = tuple[str, int, int]

# Calibrated on 120 hand-labelled attributions, stratified by margin band.
# Measured precision was ~55% in 0.2-0.3, ~64% in 0.3-0.5, then jumps to ~86%
# in 0.5-0.8 and ~88% above 0.8. The knee is at 0.5; reading the threshold off
# the coverage curve instead would have shipped roughly a third wrong labels.
DEFAULT_MIN_MARGIN = 0.5
# Tags that no ability can justify — `alliteration`, `type addition human`,
# `40k model` — are properties of a card's name or type line. They dominate the
# residual errors at every margin, because their members still share incidental
# token statistics, so no per-attribution threshold removes them. What does
# separate them is that they resolve almost none of their members: at margin 0.5
# `alliteration` resolves 2% of its 2,763 multi-ability members while `morbid`
# resolves 77%. A tag below this floor has no ability-level meaning and is
# dropped whole, single-ability members included.
DEFAULT_MIN_RESOLUTION_RATE = 0.5
# Below this many multi-ability members the resolution rate is too noisy to
# judge a tag by, so the tag is kept.
_MIN_RATE_SAMPLE = 8
# Below this a tag's token distribution is noise rather than a concept. It gates
# only multi-ability attribution: a member with a single ability needs no
# evidence, so small tags keep those.
DEFAULT_MIN_MEMBERS = 20
# A token on fewer abilities than this corpus-wide is a proper noun from one
# card. Without the floor the top-lift tokens for `mana dork` are "rasputin",
# "dream", "powerstone".
_MIN_GLOBAL_DF = 25
_MIN_LOCAL_COUNT = 3
# What an ability's token contributes when the tag never lifted it. Mildly
# negative so that off-concept text is penalised rather than merely ignored.
_UNKNOWN_TOKEN_LIFT = -0.5
# A described tag's own words are direct evidence; this floors their lift.
_ANCHOR_TOKEN_LIFT = 1.5

_TOKEN = re.compile(r"[a-z0-9']+")
# True function words only. Domain words ("mana", "creature", "target") are
# deliberately kept: lift already divides by global frequency, so a ubiquitous
# word scores ~0 on its own, and "mana" is exactly the token that identifies a
# mana dork.
_STOPWORDS = frozenset(
    """a an the of to and or is are was be been it its this that these those
    them they he she his her you your my our their as at by for from in into
    on onto with without than then so if but not no nor do does did have has
    had will would can could may might must shall should there here who whom
    which what when where why how all any both each few more most other some
    such only own same too very""".split()
)


def _tokenize(text: str) -> frozenset[str]:
    """Content tokens, falling back to every token when that leaves nothing.

    "End the turn." is entirely function words under a naive filter, and an
    ability that tokenizes to the empty set cannot be scored at all — which is
    how a prototype produced margins of +100 from a sentinel score.
    """
    raw = _TOKEN.findall(text.lower())
    content = {t for t in raw if t not in _STOPWORDS and len(t) > 1}
    return frozenset(content or raw)


def _score(tokens: frozenset[str], lift: Mapping[str, float]) -> float:
    if not tokens:
        return _UNKNOWN_TOKEN_LIFT
    return sum(lift.get(t, _UNKNOWN_TOKEN_LIFT) for t in tokens) / len(tokens)


def attribute_tags_to_abilities(
    ability_texts: Mapping[AbilityIdentity, str],
    tag_members: Mapping[str, Sequence[FaceIdentity]],
    tag_descriptions: Mapping[str, str | None] | None = None,
    *,
    min_margin: float = DEFAULT_MIN_MARGIN,
    min_members: int = DEFAULT_MIN_MEMBERS,
    min_resolution_rate: float = DEFAULT_MIN_RESOLUTION_RATE,
) -> dict[str, list[AbilityIdentity]]:
    """Map each tag to the specific abilities that carry it.

    Returns one ability per member face, or none for that face when the
    evidence does not separate its abilities. A face with a single ability is
    attributed unconditionally — there is nothing to choose between. A tag that
    resolves too few of its multi-ability members is dropped entirely.
    """
    tag_descriptions = tag_descriptions or {}

    face_abilities: dict[FaceIdentity, list[tuple[AbilityIdentity, frozenset[str]]]] = defaultdict(list)
    global_df: Counter[str] = Counter()
    for ability_key, text in ability_texts.items():
        tokens = _tokenize(text)
        face_abilities[(ability_key[0], ability_key[1])].append((ability_key, tokens))
        global_df.update(tokens)
    total_abilities = len(ability_texts)
    if not total_abilities:
        return {}

    attributed: dict[str, list[AbilityIdentity]] = {}
    resolved = ambiguous = free = 0
    dropped_tags = 0

    for tag_name, members in tag_members.items():
        faces = [f for f in members if f in face_abilities]
        if not faces:
            attributed[tag_name] = []
            continue

        singles = [face_abilities[f][0][0] for f in faces if len(face_abilities[f]) == 1]
        multis = [f for f in faces if len(face_abilities[f]) > 1]
        picks = list(singles)
        multi_resolved = 0

        if multis and len(faces) >= min_members:
            lift = _lift_map(faces, face_abilities, global_df, total_abilities)
            for token in _tokenize(f"{tag_name.replace('-', ' ')} {tag_descriptions.get(tag_name) or ''}"):
                if global_df[token] >= _MIN_GLOBAL_DF:
                    lift[token] = max(lift.get(token, 0.0), _ANCHOR_TOKEN_LIFT)
            for face in multis:
                ranked = sorted(
                    face_abilities[face],
                    key=lambda entry: _score(entry[1], lift),
                    reverse=True,
                )
                best, second = ranked[0], ranked[1]
                if _score(best[1], lift) - _score(second[1], lift) >= min_margin:
                    picks.append(best[0])
                    multi_resolved += 1

        if len(multis) >= _MIN_RATE_SAMPLE and multi_resolved / len(multis) < min_resolution_rate:
            # No ability-level meaning — see DEFAULT_MIN_RESOLUTION_RATE.
            attributed[tag_name] = []
            dropped_tags += 1
            ambiguous += len(multis)
            continue

        free += len(singles)
        resolved += multi_resolved
        ambiguous += len(multis) - multi_resolved
        attributed[tag_name] = picks

    logger.info(
        "Attributed tags to abilities. tags=%d dropped_tags=%d single_ability=%d resolved=%d "
        "dropped_ambiguous=%d margin=%.2f",
        len(attributed),
        dropped_tags,
        free,
        resolved,
        ambiguous,
        min_margin,
    )
    return attributed


def _lift_map(
    faces: Sequence[FaceIdentity],
    face_abilities: Mapping[FaceIdentity, list[tuple[AbilityIdentity, frozenset[str]]]],
    global_df: Mapping[str, int],
    total_abilities: int,
) -> dict[str, float]:
    local_df: Counter[str] = Counter()
    local_total = 0
    for face in faces:
        for _, tokens in face_abilities[face]:
            local_df.update(tokens)
            local_total += 1
    if not local_total:
        return {}
    return {
        token: math.log((count / local_total) / (global_df[token] / total_abilities))
        for token, count in local_df.items()
        if count >= _MIN_LOCAL_COUNT and global_df.get(token, 0) >= _MIN_GLOBAL_DF
    }
