"""Build data/cards.json.gz + data/vectors.npz from Scryfall's default-cards bulk file.

Each card is exactly v2's `/card/{oracle_id}` body plus internal `_` fields the serve side needs:
- card: `_color_identity` (str, WUBRG order), `_keywords` (Scryfall `keywords` list)
- face: `_type_categories` (sorted primary types), `_hashes` (`text_hash` per v2 `card_face_abilities` row).
  `_hashes` is 1:1 with `abilities`, except a face with no rules text: `abilities` is [] and `_hashes` holds the
  single `emptyoracle` placeholder, which keeps vanilla faces retrievable (v2 did the same).

Local:   uv run python -m app.build [--bulk PATH.jsonl(.gz)] [--model model] [--out data]
Worker:  python -m app.build --publish
         Builds a snapshot into the bucket (see app/snapshot.py) with the model named by `model.json` and flips
         current.json. When that model is the live one, vectors of texts already in the live snapshot are reused, so a
         daily refresh embeds only new card text; a newly promoted model re-embeds everything.
Promote: python -m app.build --promote MODEL_ID
         Points model.json at a model already under models/ (train.train uploads there). Rollback = promote the old id.
Bootstrap: python -m app.build --publish --model-id ID --model DIR
         Uploads DIR as models/ID if the bucket lacks it, promotes it and publishes.
"""

import argparse
import gzip
import json
import os
import tempfile
import time
import urllib.request
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np

from app import snapshot
from app.text import build_face_abilities

BULK_DATA_URL = "https://api.scryfall.com/bulk-data/default-cards"
# Scryfall rejects requests without an explicit User-Agent and Accept header (HTTP 400/403).
SCRYFALL_HEADERS = {"User-Agent": "OracleTutor/3.0.0 (+https://oracletutor.org)", "Accept": "application/json"}
SKIPPED_LAYOUTS = {"token", "double_faced_token", "art_series", "emblem", "planar", "scheme", "vanguard"}
PAPER_FORMATS = ("standard", "pioneer", "modern", "legacy", "vintage", "commander", "pauper")
TYPE_CATEGORIES = {"creature", "instant", "sorcery", "enchantment", "artifact", "planeswalker", "land"}
WUBRG = "WUBRG"


def _open(url_or_path: str):
    if os.path.exists(url_or_path):
        return gzip.open(url_or_path, "rb") if url_or_path.endswith(".gz") else open(url_or_path, "rb")
    # Served as application/gzip without Content-Encoding, so the stream is still compressed.
    return gzip.GzipFile(fileobj=urllib.request.urlopen(urllib.request.Request(url_or_path, headers=SCRYFALL_HEADERS)))


def iter_bulk(url_or_path: str) -> Iterator[dict]:
    with _open(url_or_path) as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def should_skip_card(card: dict) -> bool:
    """True for records that are not playable paper game pieces (tokens, Alchemy, Jumpstart theme cards...)."""
    if card.get("layout") in SKIPPED_LAYOUTS:
        return True
    faces = card.get("card_faces") or []
    games = card.get("games")
    # Some paper cards (Vintage Masters reprints) are listed MTGO-only on a printing; paper legality keeps them.
    if isinstance(games, list) and "paper" not in games:
        legalities = card.get("legalities") or {}
        if not any(legalities.get(f) in ("legal", "restricted", "banned") for f in PAPER_FORMATS):
            return True
    # Arena-rebalanced cards.
    if any((c.get("name") or "").strip().startswith("A-") for c in [card, *faces]):
        return True
    # Digital-only fallback: an Arena id but no paper/market identifiers.
    paper_ids = ("mtgo_id", "tcgplayer_id", "cardmarket_id")
    if card.get("arena_id") is not None and not card.get("multiverse_ids") and all(card.get(k) is None for k in paper_ids):
        return True
    # Jumpstart theme/pack marker cards present as `type_line: "Card"`.
    return any((c.get("type_line") or "").strip() == "Card" for c in [card, *faces])


def select_best_printing(current: dict, candidate: dict) -> dict:
    """Paper over digital, then oldest release, then lowest collector number; ties keep `current`."""
    curr_paper = "paper" in (current.get("games") or [])
    cand_paper = "paper" in (candidate.get("games") or [])
    if curr_paper != cand_paper:
        return current if curr_paper else candidate
    curr_date = current.get("released_at") or "9999-99-99"
    cand_date = candidate.get("released_at") or "9999-99-99"
    if curr_date != cand_date:
        return candidate if cand_date < curr_date else current
    curr_cn = current.get("collector_number") or "zzzz"
    cand_cn = candidate.get("collector_number") or "zzzz"
    try:
        curr_key, cand_key = int(curr_cn), int(cand_cn)
    except ValueError:
        curr_key, cand_key = curr_cn, cand_cn
    return candidate if cand_key < curr_key else current  # pyright: ignore[reportOperatorIssue]


def type_categories(type_line: str | None) -> list[str]:
    # Primary types always sit left of the em dash; supertypes and odd words are dropped.
    lhs = (type_line or "").split("—", 1)[0]
    return sorted({w.lower() for w in lhs.split()} & TYPE_CATEGORIES)


def _float(value) -> float | None:
    return None if value is None else float(value)


def derive_card(p: dict, texts: dict[str, str]) -> dict:
    """One best printing -> v2 `/card` body + `_` fields. Records each ability's hash -> normalized_text in `texts`."""
    oracle_id = p["oracle_id"]
    faces = []
    for face_ix, f in enumerate(p.get("card_faces") or [p]):
        abilities = build_face_abilities(
            oracle_text=f.get("oracle_text"), card_name=f.get("name") or "", type_line=f.get("type_line") or ""
        )
        for a in abilities:
            texts[a.text_hash] = a.normalized_text
        faces.append({
            "oracle_id": oracle_id,
            "face_ix": face_ix,
            "name": f.get("name"),
            "mana_cost": f.get("mana_cost"),
            "type_line": f.get("type_line"),
            "oracle_text": f.get("oracle_text"),
            "power": f.get("power"),
            "toughness": f.get("toughness"),
            "loyalty": f.get("loyalty"),
            "defense": f.get("defense"),
            "colors": f.get("colors"),
            "color_indicator": f.get("color_indicator"),
            "image_uris": f.get("image_uris"),
            "artist": f.get("artist"),
            "flavor_text": f.get("flavor_text"),
            "cmc": _float(f.get("cmc")),
            "abilities": [
                {"ability_ix": a.ability_ix, "text": a.text, "is_keyword": a.is_keyword} for a in abilities if a.text
            ],
            "_type_categories": type_categories(f.get("type_line")),
            "_hashes": [a.text_hash for a in abilities],
        })
    return {
        "oracle_id": oracle_id,
        "scryfall_id": p["id"],
        "name": p.get("name"),
        "layout": p.get("layout"),
        "cmc": _float(p.get("cmc")),
        "edhrec_rank": p.get("edhrec_rank"),
        "rarity": p.get("rarity"),
        "legalities": p.get("legalities"),
        "set_code": p.get("set"),
        "border_color": p.get("border_color"),
        "faces": faces,
        "_color_identity": "".join(c for c in WUBRG if c in (p.get("color_identity") or [])),
        "_keywords": p.get("keywords"),
    }


def build_cards(printings: Iterable[dict]) -> tuple[list[dict], dict[str, str]]:
    """Reduce printings to one per oracle_id and derive cards (sorted by oracle_id) + distinct hash -> text."""
    best: dict[str, dict] = {}
    for card in printings:
        oracle_id = card.get("oracle_id")
        if not oracle_id or should_skip_card(card):
            continue
        best[oracle_id] = select_best_printing(best[oracle_id], card) if oracle_id in best else card
    texts: dict[str, str] = {}
    cards = [derive_card(best[oid], texts) for oid in sorted(best)]
    return cards, texts


def embed(texts: dict[str, str], model_dir: Path, known: dict[str, np.ndarray] | None = None):
    """Vectors for every hash, sorted by hash. `known` vectors (same model) are reused instead of re-encoded."""
    from app.encoder import Encoder

    known = known or {}
    hashes = sorted(texts)
    todo = [h for h in hashes if h not in known]
    print(f"embedding {len(todo)} new texts, reusing {len(hashes) - len(todo)}", flush=True)
    encoded = {}
    if todo:
        # Encode in length order so each batch pads to similar lengths.
        todo.sort(key=lambda h: len(texts[h]))
        vectors = Encoder(model_dir, threads=os.cpu_count() or 1).encode([texts[h] for h in todo])
        encoded = dict(zip(todo, vectors.astype(np.float16)))
    return np.array(hashes), np.stack([known[h] if h in known else encoded[h] for h in hashes]).astype(np.float16)


def write(out: Path, cards: list[dict], updated_at: str | None, model_id: str, hashes, vectors) -> None:
    out.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"bulk_updated_at": updated_at, "model": model_id, "cards": cards}, ensure_ascii=False)
    (out / "cards.json.gz").write_bytes(gzip.compress(payload.encode(), mtime=0))
    np.savez(out / "vectors.npz", hashes=hashes, vectors=vectors, model=np.array(model_id))


def latest_bulk() -> tuple[str, str]:
    meta = json.load(urllib.request.urlopen(urllib.request.Request(BULK_DATA_URL, headers=SCRYFALL_HEADERS)))
    return meta["jsonl_download_uri"], meta["updated_at"]


def promote(model_id: str) -> None:
    if not snapshot.has_model(model_id):
        raise SystemExit(f"models/{model_id}/ is not in the bucket; train.train uploads models there")
    snapshot.write_promoted({"model": model_id, "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    print(f"promoted {model_id}; the next refresh run re-embeds with it")


def publish(override: str | None, local_model: Path, keep: int = 5) -> None:
    cache = Path(os.environ.get("CACHE_DIR") or Path(tempfile.gettempdir()) / "oracle-tutor")
    if override:
        model_id = override
        if not snapshot.has_model(model_id):
            if not (local_model / snapshot.MODEL_FILES[0]).exists():
                raise SystemExit(f"models/{model_id}/ is not in the bucket and {local_model} holds no model")
            print(f"uploading model {model_id}", flush=True)
            snapshot.upload_model(local_model, model_id)
        promote(model_id)
    else:
        promoted = snapshot.read_promoted()
        if not promoted:
            raise SystemExit(f"no {snapshot.PROMOTED} in the bucket; run --promote MODEL_ID first")
        model_id: str = promoted["model"]
    live = snapshot.read_pointer()
    source, updated_at = latest_bulk()
    if live and live["model"] == model_id and live["scryfall"] == updated_at:
        print(f"snapshot {live['snapshot']} is current (model {model_id}, scryfall {updated_at}); nothing to do")
        return
    model_dir = snapshot.download_model(model_id, cache)

    print(f"downloading {source}", flush=True)
    cards, texts = build_cards(iter_bulk(source))
    known = {}
    if live and live["model"] == model_id:
        with np.load(snapshot.download_data(live["snapshot"], cache) / "vectors.npz") as prev:
            known = dict(zip(prev["hashes"].tolist(), prev["vectors"]))
    hashes, vectors = embed(texts, model_dir, known)

    snapshot_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = cache / "snapshots" / snapshot_id
    write(out, cards, updated_at, model_id, hashes, vectors)
    snapshot.upload_data(out, snapshot_id)
    snapshot.write_pointer({"snapshot": snapshot_id, "model": model_id, "scryfall": updated_at})
    snapshot.prune_snapshots(keep)
    print(f"published snapshot {snapshot_id}: {len(cards)} cards, {len(hashes)} texts, model {model_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bulk", help="local Scryfall default-cards .jsonl(.gz); downloads the latest when omitted")
    parser.add_argument("--model", default="model", help="local model dir")
    parser.add_argument("--model-id", help="model label; with --publish, a bucket model id to promote and publish")
    parser.add_argument("--out", default="data")
    parser.add_argument("--publish", action="store_true", help="build a snapshot into the bucket and make it live")
    parser.add_argument("--promote", metavar="MODEL_ID", help="point model.json at this bucket model and exit")
    args = parser.parse_args()

    if args.promote:
        promote(args.promote)
        return
    if args.publish:
        publish(args.model_id, Path(args.model))
        return

    source, updated_at = (args.bulk, None) if args.bulk else latest_bulk()
    print(f"reading {source}", flush=True)
    cards, texts = build_cards(iter_bulk(source))
    print(f"{len(cards)} cards, {sum(len(f['_hashes']) for c in cards for f in c['faces'])} abilities, "
          f"{len(texts)} distinct texts", flush=True)
    model_id = args.model_id or Path(args.model).resolve().name
    hashes, vectors = embed(texts, Path(args.model))
    write(Path(args.out), cards, updated_at, model_id, hashes, vectors)
    print(f"wrote {args.out}/cards.json.gz, {args.out}/vectors.npz ({vectors.shape})")


if __name__ == "__main__":
    main()
