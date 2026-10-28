import gzip
import json
import random
import re
from collections import Counter
from pathlib import Path

import numpy as np

from app.text import _QUERY_SEPARATOR, EMPTY_ORACLE_TOKEN, _ability_sources, normalize_oracle_text

CARD_TYPES = {"c": "creature", "i": "instant", "s": "sorcery", "e": "enchantment", "a": "artifact",
              "p": "planeswalker", "l": "land"}
FORMATS = {"s": "standard", "p": "pioneer", "m": "modern", "l": "legacy", "v": "vintage", "c": "commander",
           "u": "pauper"}
RARITIES = {"c": "common", "u": "uncommon", "r": "rare", "m": "mythic"}
_COLOR_BITS = {c: 1 << i for i, c in enumerate("WUBRG")}

# How far below the best-matching ability another ability may sit and still be
# considered "matched just as well" when picking which one to show the user.
_DISPLAY_SIMILARITY_MARGIN = 0.05
# Rejected-ability band. Cosine similarity between short ability texts has a
# high floor — "Flying" scores ~0.67 against "Vigilance" and ~0.74 against
# "Shadow" — so a raw `1 - sim` penalty would shave every card by two thirds and
# make the reported match percentage meaningless. Only the band above the floor
# carries signal: exact restatements sit at 0.99+, compound lines that contain
# it ("Flying; fear") at ~0.84, and everything unrelated below 0.78. So
# similarity is ramped linearly across the band and anything at the top is
# dropped outright — "not this ability" has to actually remove the cards that
# print it, not just rank them lower.
_REJECT_IGNORE_SIMILARITY = 0.70
_REJECT_EXCLUDE_SIMILARITY = 0.90
# Corpus text renders {T} type-aware ("tap this creature" / "tap this land"),
# but a typed query has no type line. Each query ability is encoded once per
# distinct self-reference and scored by its best variant, so "{T}: Add {G}."
# finds both Llanowar Elves and Forest instead of matching neither exactly.
# Text without {T}/{Q} renders identically for every type: one variant, no cost.
_SELF_REFERENCE_TYPES = ("Creature", "Land", "Artifact", "Planeswalker", "Enchantment", "Instant", "")

_ABILITY_WORD = re.compile(r"^\s*([A-Za-z][A-Za-z' -]{1,40}?)\s+[—-]\s+", re.MULTILINE)
_HOME_POOL_SIZE = 300


def query_abilities(q: str | None) -> list[tuple[str, list[str]]]:
    """(display text, normalized variants) per query ability, via the corpus's own segmentation and normalization.

    `//` separates abilities; keyword lists, modal bullets, keyword expansion and
    overload all apply exactly as they do to card text.
    """
    out, seen = [], set()
    for display, source in _ability_sources(_QUERY_SEPARATOR.sub("\n", q or "")):
        variants = list(dict.fromkeys(normalize_oracle_text(source, type_line=t) for t in _SELF_REFERENCE_TYPES))
        if variants[0] != EMPTY_ORACLE_TOKEN and tuple(variants) not in seen:
            seen.add(tuple(variants))
            out.append((display, variants))
    return out


def _color_bits(colors: list[str] | str | None) -> int:
    # -1 stands for NULL: Postgres `@>`/`<@` against NULL is never true, so v2 never matched it.
    return -1 if colors is None else sum(_COLOR_BITS.get(c, 0) for c in set(colors))


def _home_term(term: str) -> str:
    return " ".join(term.split()).strip(" -—")


class Index:
    def __init__(self, cards: list[dict], hashes, vectors, encoder, model: str = "", bulk_updated_at=None):
        self.encoder, self.model, self.bulk_updated_at = encoder, model, bulk_updated_at
        self.snapshot: str | None = None
        self.cards = {c["oracle_id"]: c for c in cards}
        self.vectors = np.asarray(vectors, dtype=np.float32)
        row_of = {h: i for i, h in enumerate(hashes)}

        all_faces = [(c, f) for c in cards for f in c["faces"]]
        self.faces = sorted(((c, f) for c, f in all_faces if f["_hashes"]),
                            key=lambda cf: (cf[0]["oracle_id"], cf[1]["face_ix"]))
        self.face_pos = {(c["oracle_id"], f["face_ix"]): i for i, (c, f) in enumerate(self.faces)}
        # Flat CSR layout: instances ordered by face, so a per-face aggregate is one `reduceat`.
        inst_hashes = [h for _, f in self.faces for h in f["_hashes"]]
        self.starts = np.cumsum([0] + [len(f["_hashes"]) for _, f in self.faces[:-1]])
        self.ends = self.starts + np.array([len(f["_hashes"]) for _, f in self.faces])
        self.inst_row = np.array([row_of[h] for h in inst_hashes], dtype=np.int64)
        self.inst_text = [f["abilities"][i]["text"] if i < len(f["abilities"]) else ""
                          for _, f in self.faces for i in range(len(f["_hashes"]))]
        # log1p(N/df) over ability instances: "Flying" (df~3235) lands near 2.5
        # while a one-off ability lands near 11, so distinctive text dominates
        # without common text being zeroed out. Weighting by frequency rather than
        # keyword-ness, because "Enchant creature" and "{T}: Add {C}." swamp
        # results just as badly as "Flying".
        df = Counter(inst_hashes)
        self.inst_idf = np.array([np.log1p(len(inst_hashes) / df[h]) for h in inst_hashes], dtype=np.float32)

        self.is_type = {t: np.array([t in (f["_type_categories"] or []) for _, f in self.faces])
                        for t in CARD_TYPES.values()}
        self.legal = {fmt: np.array([(c["legalities"] or {}).get(fmt) in ("legal", "restricted") for c, _ in self.faces])
                      for fmt in FORMATS.values()}
        self.rarity = np.array([c["rarity"] or "" for c, _ in self.faces])
        self.popularity = np.array([c["edhrec_rank"] or np.inf for c, _ in self.faces])
        self.cmc = np.array([np.nan if c["cmc"] is None else c["cmc"] for c, _ in self.faces], dtype=np.float64)
        self.identity = np.array([_color_bits(c["_color_identity"]) for c, _ in self.faces])
        self.face_colors = np.array([_color_bits(f["colors"]) for _, f in self.faces])

        self.name_order = sorted(
            ((f["name"].lower(), c, f) for c, f in all_faces),
            key=lambda m: (m[1]["edhrec_rank"] is None, m[1]["edhrec_rank"] or 0, m[1]["name"], m[2]["face_ix"],
                           m[2]["name"]),
        )
        self.oracle_texts = [f["oracle_text"] for _, f in all_faces if f["oracle_text"] and f["oracle_text"].strip()]
        self.keyword_lists = [c["_keywords"] for c in cards if c["_keywords"] is not None]

    def mask(self, card_type=None, colors=None, cmc_min=None, cmc_max=None, formats=None, rarity=None,
             color_feature="identity", match_mode="at_least") -> np.ndarray:
        alive = np.ones(len(self.faces), dtype=bool)
        if card_type:
            alive &= np.logical_or.reduce([self.is_type[t] for t in card_type])
        wanted = _color_bits([c for c in (colors or "").upper() if c in _COLOR_BITS])
        if wanted:
            have = self.identity if color_feature == "identity" else self.face_colors
            if match_mode == "exact":
                alive &= have == wanted
            elif match_mode == "at_most":
                alive &= (have >= 0) & ((have & ~wanted) == 0)
            else:
                alive &= (have >= 0) & ((have & wanted) == wanted)
        # NaN cmc compares false, matching SQL's `cmc IS NOT NULL AND ...`.
        if cmc_min is not None:
            alive &= self.cmc >= cmc_min
        if cmc_max is not None:
            alive &= self.cmc <= cmc_max
        if formats:
            alive &= np.logical_or.reduce([self.legal[f] for f in formats])
        if rarity:
            alive &= np.isin(self.rarity, rarity)
        return alive

    def similar_to_face(self, oracle_id: str, face_ix: int, limit: int, alive: np.ndarray,
                        include: list[int] | None = None, exclude: list[int] | None = None):
        """Faces whose *ability set* resembles this face's, by bidirectional Chamfer.

        `include` narrows the seed; `exclude` names abilities the user does not
        want — dropped from the seed and penalized on the candidate side. Exclude
        wins when an ability is in both. Scoring only switches to forward when
        the selection genuinely narrows the ability set: having asked for cards
        that *have* these abilities, the user should not see them demoted for
        also doing things they never ruled out.
        """
        pos = self.face_pos.get((oracle_id, face_ix))
        if pos is None:
            return []
        start, n = int(self.starts[pos]), int(self.ends[pos] - self.starts[pos])
        rejected = sorted({i for i in exclude or () if i < n})
        seed_ixs = [i for i in (include or range(n)) if i < n and i not in rejected]
        if not seed_ixs:
            return []
        seed = start + np.array(seed_ixs)
        alive = alive.copy()
        alive[pos] = False
        reject = self.vectors[self.inst_row[start + np.array(rejected)]] if rejected else None
        return self._score(self.vectors[self.inst_row[seed]], np.arange(len(seed_ixs)), self.inst_idf[seed],
                           len(seed_ixs) == n, alive, reject, limit)

    def search_text(self, abilities: list[tuple[str, list[str]]], limit: int, alive: np.ndarray):
        """Faces that *have* abilities matching the query, forward-only (AND across query abilities).

        Max-pooled rather than bidirectional: someone searching "draw a card when
        a creature dies" should not see cards demoted for also having flying.
        The seed side is NOT IDF-weighted: the user typed each ability on purpose.
        """
        if not abilities:
            return []
        seed = self.encoder.encode([v for _, variants in abilities for v in variants])
        col_starts = np.cumsum([0] + [len(variants) for _, variants in abilities[:-1]])
        return self._score(seed, col_starts, None, False, alive, None, limit)

    def _score(self, seed, col_starts, seed_weights, bidirectional, alive, reject, limit):
        """Score every eligible face; nothing is truncated before filtering.

        Chamfer mean over ability sets:
        * forward  = mean over SEED abilities of their best match on this face ("how much of the seed is covered?")
        * backward = mean over this face's abilities of their best seed match ("how much of the card is explained?")
        Card-to-card averages both, so a card matching one ability and doing five
        unrelated things scores below one that matches throughout. Both means are
        IDF-weighted. Seed columns sharing a `col_starts` group are variants of
        one ability; the best variant counts.
        """
        # One matmul over distinct texts, then gathered onto instances.
        sims = (self.vectors @ np.asarray(seed, dtype=np.float32).T)[self.inst_row]
        per_seed_best = np.maximum.reduceat(np.maximum.reduceat(sims, self.starts, axis=0), col_starts, axis=1)
        if seed_weights is None:
            forward = per_seed_best.mean(axis=1)
        else:
            forward = per_seed_best @ seed_weights / seed_weights.sum()
        instance_best = sims.max(axis=1)
        if bidirectional:
            backward = (np.add.reduceat(instance_best * self.inst_idf, self.starts)
                        / np.add.reduceat(self.inst_idf, self.starts))
            scores = (forward + backward) / 2.0
        else:
            scores = forward

        if reject is not None:
            rejection = np.maximum.reduceat((self.vectors @ reject.T)[self.inst_row].max(axis=1), self.starts)
            # Scale rather than subtract, so the score stays a percentage. The scale
            # reaches zero exactly where the hard drop begins, so the two are continuous.
            band = _REJECT_EXCLUDE_SIMILARITY - _REJECT_IGNORE_SIMILARITY
            scores = scores * (1.0 - np.clip((rejection - _REJECT_IGNORE_SIMILARITY) / band, 0.0, 1.0))
            alive = alive & (rejection < _REJECT_EXCLUDE_SIMILARITY)

        candidates = np.flatnonzero(alive)
        rounded = np.round(scores[candidates], 4)  # float16 vectors leave ~1e-5 noise on exact ties
        # Exact ties are common (every vanilla "Flying" card scores 1.0 for "flying"), so
        # break them by EDHREC rank: popular cards first, and a deterministic order.
        top = candidates[np.lexsort((self.popularity[candidates], -rounded))[:max(limit, 0)]]
        return [(*self.faces[p], round(float(scores[p]), 6), self._display_ability(instance_best, p)) for p in top]

    def _display_ability(self, instance_best: np.ndarray, pos: int) -> str | None:
        """Which ability to SHOW: relevance gates, distinctiveness breaks ties.

        Raw argmax reports "Flying" for every flier (a keyword self-match is ~1.0);
        a pure IDF argmax reports the most obscure ability even when it barely
        matched. So keep abilities within the margin of the best, then prefer the
        most distinctive.
        """
        start, end = int(self.starts[pos]), int(self.ends[pos])
        segment = instance_best[start:end]
        ranked = np.where(segment >= segment.max() - _DISPLAY_SIMILARITY_MARGIN, self.inst_idf[start:end], -np.inf)
        return self.inst_text[start + int(np.argmax(ranked))] or None

    def search_names(self, q: str, limit: int, offset: int):
        """v2's ILIKE ranking: exact name, then prefix, then substring; edhrec rank breaks ties (presorted)."""
        ql = q.strip().lower()
        if not ql:
            return []
        hits = [m for m in self.name_order if ql in m[0]]
        hits.sort(key=lambda m: 0 if m[0] == ql else 1 if m[0].startswith(ql) else 2)
        return [(c, f) for _, c, f in hits[offset:offset + limit]]

    def oracle_samples(self, n: int) -> tuple[list[str], list[str]]:
        """Homepage samples: random oracle texts, plus keywords and ability words drawn from a random slice."""
        texts = random.sample(self.oracle_texts, min(_HOME_POOL_SIZE, len(self.oracle_texts)))
        terms: dict[str, str] = {}
        for keywords in random.sample(self.keyword_lists, min(_HOME_POOL_SIZE, len(self.keyword_lists))):
            for kw in keywords:
                if term := _home_term(kw):
                    terms.setdefault(term.casefold(), term)
        for text in texts:
            for m in _ABILITY_WORD.finditer(text):
                if term := _home_term(m.group(1)):
                    terms.setdefault(term.casefold(), term)
        pool = list(terms.values())
        return texts[:n], random.sample(pool, min(n, len(pool)))


def load(data_dir: Path, encoder) -> Index:
    with gzip.open(data_dir / "cards.json.gz") as fh:
        payload = json.load(fh)
    npz = np.load(data_dir / "vectors.npz")
    return Index(payload["cards"], npz["hashes"].tolist(), npz["vectors"], encoder, str(npz["model"]),
                 payload["bulk_updated_at"])
