import asyncio
import html
import json
import os
import re
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from app import search, snapshot
from app.encoder import Encoder
from app.text import MAX_QUERY_ABILITIES

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "model"))
STATIC_DIR = Path(os.environ.get("STATIC_DIR", "static"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
CACHE_DIR = Path(os.environ.get("CACHE_DIR") or Path(tempfile.gettempdir()) / "oracle-tutor")
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "300"))

MAX_QUERY_LENGTH = 200
MAX_FILTER_CODE_LENGTH = 16
MAX_ABILITY_SELECTION_LENGTH = 64
DOUBLE_SIDED_LAYOUTS = frozenset({"transform", "modal_dfc", "meld", "double_faced_token", "art_series"})

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: https:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; upgrade-insecure-requests"
    ),
}


def _load_snapshot(pointer: dict, encoder: Encoder | None) -> search.Index:
    """Download (or reuse from disk) the pointer's model + data and build a complete index off to the side."""
    model_dir = snapshot.download_model(pointer["model"], CACHE_DIR)
    if encoder is None or encoder.model_dir != model_dir:
        encoder = Encoder(model_dir)
    index = search.load(snapshot.download_data(pointer["snapshot"], CACHE_DIR), encoder)
    index.snapshot = pointer["snapshot"]
    for stale in (CACHE_DIR / "snapshots").iterdir():
        if stale.name != pointer["snapshot"]:
            shutil.rmtree(stale, ignore_errors=True)
    return index


async def _follow_pointer(app: FastAPI) -> None:
    """Swap in each snapshot the refresh worker publishes. The old index serves until the new one is fully built;
    the swap is a single reference assignment, so a request sees one index or the other, never a mix."""
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            pointer = await asyncio.to_thread(snapshot.read_pointer)
            if pointer and pointer["snapshot"] != app.state.index.snapshot:
                app.state.index = await asyncio.to_thread(_load_snapshot, pointer, app.state.index.encoder)
                print(f"swapped to snapshot {pointer['snapshot']} (model {pointer['model']})", flush=True)
        except Exception as exc:  # noqa: BLE001 - keep serving the current snapshot; retry next poll
            print(f"snapshot poll failed: {exc!r}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not snapshot.enabled():
        app.state.index = search.load(DATA_DIR, Encoder(MODEL_DIR))
        yield
        return
    pointer = snapshot.read_pointer()
    if pointer is None:
        raise RuntimeError("bucket has no current.json yet; run the refresh worker once (python -m app.build --publish)")
    app.state.index = _load_snapshot(pointer, None)
    poller = asyncio.create_task(_follow_pointer(app))
    yield
    poller.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
api = APIRouter(prefix="/api")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


def _image_side(card: dict, face: dict) -> str:
    return "back" if card["layout"] in DOUBLE_SIDED_LAYOUTS and face["face_ix"] > 0 else "front"


def _parse_codes(raw: str | None, value_map: dict[str, str], field: str) -> list[str] | None:
    codes = list((raw or "").strip().lower())
    if not codes:
        return None
    invalid = [c for c in codes if c not in value_map]
    if invalid:
        raise HTTPException(422, f"Invalid {field} codes: {', '.join(invalid)}")
    if len(codes) != len(set(codes)):
        raise HTTPException(422, f"Duplicate {field} codes in filter")
    return [value_map[c] for c in codes]


def _parse_rarity(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    chars = list(raw.lower())
    invalid = [c for c in chars if c not in search.RARITIES]
    if invalid:
        raise HTTPException(422, f"Invalid rarity characters: {', '.join(invalid)!r}. Use c, u, r, m.")
    if len(chars) != len(set(chars)):
        raise HTTPException(422, "Duplicate rarity characters in rarity filter")
    return [search.RARITIES[c] for c in chars]


def _parse_ability_ixs(raw: str | None, field: str) -> list[int] | None:
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    if not parts:
        return None
    try:
        values = [int(p) for p in parts]
    except ValueError:
        raise HTTPException(422, f"Invalid {field}: expected comma-separated integers") from None
    if any(v < 0 for v in values):
        raise HTTPException(422, f"Invalid {field}: indices must be non-negative")
    return sorted(set(values))


def _public(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


@api.get("/ready")
def ready(request: Request):
    index = request.app.state.index
    return {"ready": True, "model": index.model, "data": index.bulk_updated_at, "snapshot": index.snapshot}


@api.get("/oracle-samples")
def oracle_samples(request: Request, n: int = Query(60, ge=1, le=100)):
    texts, terms = request.app.state.index.oracle_samples(n)
    return {"texts": texts, "terms": terms}


@api.get("/search")
def search_cards(
    request: Request,
    q: str = Query(..., max_length=MAX_QUERY_LENGTH),
    limit: int = Query(10, ge=1, le=25),
    offset: int = Query(0, ge=0, le=500),
):
    return [
        {"name": f["name"], "card_name": c["name"], "similarity": 1.0, "rank": c["edhrec_rank"],
         "oracle_id": c["oracle_id"], "scryfall_id": c["scryfall_id"], "face_ix": f["face_ix"],
         "image_side": _image_side(c, f)}
        for c, f in request.app.state.index.search_names(q, limit, offset)
    ]


@api.get("/card/{oracle_id}")
def get_card(request: Request, oracle_id: str):
    card = request.app.state.index.cards.get(oracle_id)
    if card is None:
        raise HTTPException(404, "Card not found")
    return {**_public(card), "faces": [_public(f) for f in card["faces"]]}


@api.get("/similar-cards")
def similar_cards(
    request: Request,
    oracle_id: str | None = None,
    face_ix: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=MAX_QUERY_LENGTH),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=500),
    card_type: str | None = Query(None, max_length=MAX_FILTER_CODE_LENGTH),
    colors: str | None = Query(None, max_length=MAX_FILTER_CODE_LENGTH),
    cmc_min: float | None = None,
    cmc_max: float | None = None,
    format: str | None = Query(None, max_length=MAX_FILTER_CODE_LENGTH),
    rarity: str | None = Query(None, max_length=MAX_FILTER_CODE_LENGTH),
    color_feature: Literal["identity", "colors"] = "identity",
    match_mode: Literal["at_least", "at_most", "exact"] = "at_least",
    include_abilities: str | None = Query(None, max_length=MAX_ABILITY_SELECTION_LENGTH),
    exclude_abilities: str | None = Query(None, max_length=MAX_ABILITY_SELECTION_LENGTH),
):
    if oracle_id is None and not (q and q.strip()):
        raise HTTPException(422, "Provide either oracle_id or q")
    abilities = search.query_abilities(q) if oracle_id is None else []
    if len(abilities) > MAX_QUERY_ABILITIES:
        raise HTTPException(
            422,
            f"Query has {len(abilities)} abilities; the limit is {MAX_QUERY_ABILITIES}. "
            "Each one costs a separate similarity probe.",
        )
    include = _parse_ability_ixs(include_abilities, "include_abilities")
    exclude = _parse_ability_ixs(exclude_abilities, "exclude_abilities")
    index = request.app.state.index
    alive = index.mask(
        card_type=_parse_codes(card_type, search.CARD_TYPES, "card type"), colors=colors, cmc_min=cmc_min,
        cmc_max=cmc_max, formats=_parse_codes(format, search.FORMATS, "format"), rarity=_parse_rarity(rarity),
        color_feature=color_feature, match_mode=match_mode,
    )

    t0 = time.monotonic()
    wanted = limit + offset + 1
    if oracle_id is not None:
        hits = index.similar_to_face(oracle_id, face_ix, wanted, alive, include, exclude)
    else:
        hits = index.search_text(abilities, wanted, alive)
    items = [
        {"oracle_id": c["oracle_id"], "scryfall_id": c["scryfall_id"], "face_ix": f["face_ix"],
         "image_side": _image_side(c, f), "name": f["name"], "card_name": c["name"], "similarity": score,
         "matched_ability": matched, "rank": c["edhrec_rank"], "type_line": f["type_line"],
         "mana_cost": f["mana_cost"], "oracle_text": f["oracle_text"], "power": f["power"],
         "toughness": f["toughness"], "colors": f["colors"], "layout": c["layout"], "rarity": c["rarity"],
         "legalities": c["legalities"], "border_color": c["border_color"], "set_code": c["set_code"]}
        for c, f, score, matched in hits[offset:offset + limit]
    ]
    filters = {k: v for k, v in {
        "card_type": card_type, "colors": colors, "cmc_min": cmc_min, "cmc_max": cmc_max, "format": format,
        "rarity": rarity, "include": include, "exclude": exclude,
    }.items() if v is not None}
    if colors:
        filters |= {"color_feature": color_feature, "match_mode": match_mode}
    seed = f"oracle_id={oracle_id} face_ix={face_ix}" if oracle_id is not None else f"q={q!r}"
    print(f"similar-cards mode={'card' if oracle_id is not None else 'text'} {seed} filters={filters} "
          f"offset={offset} results={len(items)} ms={(time.monotonic() - t0) * 1000:.0f}", flush=True)
    return {"items": items, "has_more": len(hits) > offset + limit,
            "query_abilities": [display for display, _ in abilities] or None}


app.include_router(api)


def _origin(request: Request) -> str:
    return PUBLIC_URL or str(request.base_url).rstrip("/")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request):
    origin = html.escape(_origin(request))
    # The sitemap protocol caps one file at 50,000 URLs; the corpus is ~34k oracle ids.
    ids = sorted(request.app.state.index.cards)[:49_999]
    body = "".join([
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"<url><loc>{origin}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
        *(f"<url><loc>{origin}/?card={html.escape(i)}</loc><changefreq>weekly</changefreq>"
          "<priority>0.7</priority></url>" for i in ids),
        "</urlset>",
    ])
    return Response(body, media_type="application/xml", headers={"Cache-Control": "public, max-age=3600"})


# Tags index.html ships for the homepage, replaced on card and query pages.
_DEFAULT_HEAD_TAGS = re.compile(r'\s*<title>.*?</title>|\s*<meta\s+(?:name|property)="(?:description|og:[^"]*|twitter:[^"]*)"[^>]*>', re.DOTALL)
_SITE_NAME = "Oracle Tutor"


def _head_tags(title: str, description: str, canonical: str, og_type: str, image: str | None, extra: str = "") -> str:
    t, d, u = html.escape(title), html.escape(description), html.escape(canonical)
    tags = [
        f"<title>{t}</title>", f'<meta name="description" content="{d}">', f'<link rel="canonical" href="{u}">',
        f'<meta property="og:site_name" content="{_SITE_NAME}">', f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:title" content="{t}">', f'<meta property="og:description" content="{d}">',
        f'<meta property="og:url" content="{u}">',
        f'<meta name="twitter:card" content="{"summary_large_image" if image else "summary"}">',
        f'<meta name="twitter:title" content="{t}">', f'<meta name="twitter:description" content="{d}">',
    ]
    if image:
        tags += [f'<meta property="og:image" content="{html.escape(image)}">',
                 f'<meta name="twitter:image" content="{html.escape(image)}">']
    return "\n".join(tags) + extra


def _card_head(origin: str, card: dict) -> str:
    face = card["faces"][0] if card["faces"] else {}
    type_line, oracle_text = face.get("type_line") or "", face.get("oracle_text") or ""
    source = " ".join(f"{type_line}. {oracle_text}".strip(" .").split())
    description = (source if len(source) <= 200 else source[:199].rstrip() + "…") or f"{card['name']} on {_SITE_NAME}."
    canonical = f"{origin}/?card={card['oracle_id']}"
    uris = face.get("image_uris") or {}
    sid = card["scryfall_id"]
    image = uris.get("normal") or uris.get("large") or f"https://cards.scryfall.io/normal/front/{sid[0]}/{sid[1]}/{sid}.jpg"
    ld = {"@context": "https://schema.org", "@type": "Game", "name": card["name"], "url": canonical,
          "description": description, "isPartOf": {"@type": "VideoGameSeries", "name": "Magic: The Gathering"},
          "image": image}
    if type_line:
        ld["genre"] = type_line
    if card["rarity"]:
        ld["additionalProperty"] = [{"@type": "PropertyValue", "name": "rarity", "value": card["rarity"]}]
    # `</` must not appear inside a <script> block, or card text could close it.
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    return _head_tags(f"{card['name']} | {_SITE_NAME}", description, canonical, "article", image,
                      f'\n<script type="application/ld+json">{ld_json}</script>')


def _query_head(origin: str, q: str) -> str:
    description = f'Magic: The Gathering cards matching "{q}". Semantic search by meaning on {_SITE_NAME}.'
    return _head_tags(f'"{q}" | {_SITE_NAME}', description, f"{origin}/?q={quote_plus(q)}", "website", None)


@app.get("/{path:path}", include_in_schema=False)
def spa(request: Request, path: str):
    """Built frontend: real files as-is, everything else index.html with per-page meta for link unfurls."""
    root = STATIC_DIR.resolve()
    if path == "api" or path.startswith("api/") or not root.is_dir():
        raise HTTPException(404, "Not Found")
    file = (root / path).resolve()
    if path and file.is_relative_to(root) and file.is_file():
        headers = {"Cache-Control": "public, max-age=2592000, immutable"} if path.startswith("assets/") else None
        return FileResponse(file, headers=headers)

    page = (root / "index.html").read_text()
    card = request.app.state.index.cards.get(request.query_params.get("card", ""))
    q = request.query_params.get("q", "").strip()[:MAX_QUERY_LENGTH]
    if card or q:
        head = _card_head(_origin(request), card) if card else _query_head(_origin(request), q)
        page = _DEFAULT_HEAD_TAGS.sub("", page).replace("</head>", head + "\n</head>", 1)
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})
