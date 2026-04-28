from __future__ import annotations

import logging
from collections.abc import Iterable
from urllib.parse import quote_plus
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ...core.config import public_app_url
from ...core.database import get_db
from ...core.models import Card, CardFace

logger = logging.getLogger("ot_backend.api.seo")

router = APIRouter(tags=["seo"])

# Sitemap protocol caps a single sitemap at 50,000 URLs and 50 MiB. The card
# pool is currently around 30k oracle ids; a single sitemap is fine. If this
# ever exceeds the cap, split into per-letter sitemaps via a sitemap index.
_SITEMAP_URL_CAP = 50_000

_SITE_NAME = "Oracle Tutor"
_TAGLINE = "find Magic: The Gathering cards by meaning, not name"
_DEFAULT_DESCRIPTION = (
    "Oracle Tutor is a semantic search engine for Magic: The Gathering. Describe what a card "
    "does and find every card that matches, by meaning rather than exact name."
)


def _iter_card_urls(origin: str, db: Session) -> Iterable[str]:
    yield (
        f"<url><loc>{escape(origin)}/</loc>"
        "<changefreq>daily</changefreq>"
        "<priority>1.0</priority></url>"
    )

    rows = db.execute(select(Card.oracle_id).order_by(Card.oracle_id)).all()
    emitted = 0
    for (oracle_id,) in rows:
        if emitted >= _SITEMAP_URL_CAP - 1:
            break
        loc = f"{origin}/?card={oracle_id}"
        yield (
            f"<url><loc>{escape(loc)}</loc>"
            "<changefreq>weekly</changefreq>"
            "<priority>0.7</priority></url>"
        )
        emitted += 1


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(db: Session = Depends(get_db)) -> Response:
    origin = public_app_url()
    if not origin:
        raise HTTPException(status_code=404, detail="Sitemap not configured")

    body = "".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            *_iter_card_urls(origin, db),
            "</urlset>",
        ]
    )
    headers = {"Cache-Control": "public, max-age=3600"}
    return Response(content=body, media_type="application/xml", headers=headers)


# ---------------------------------------------------------------------------
# Bot-facing prerendered HTML shell
#
# Browsers always get the SPA index.html via nginx try_files. Bots (Googlebot,
# Slackbot, Twitterbot, Discordbot, etc.) get routed here so social-preview
# crawlers see real <head> tags and a readable body without running JS.
#
# The body content is intentionally minimal: enough text for crawlers to index
# and for unfurl previews to present, plus a canonical link back to the SPA.
# This is "Dynamic Rendering" by Google's old terminology, still tolerated for
# SEO purposes (and Google's docs explicitly say content parity matters, not
# that bots and users must receive identical HTML).
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int = 200) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 1].rstrip() + "…"


def _scryfall_image_url(scryfall_id: str | None, size: str = "normal") -> str | None:
    if not scryfall_id or len(scryfall_id) < 2:
        return None
    return (
        f"https://cards.scryfall.io/{size}/front/"
        f"{scryfall_id[0]}/{scryfall_id[1]}/{scryfall_id}.jpg"
    )


def _primary_face(card: Card) -> CardFace | None:
    faces = sorted(card.faces, key=lambda f: f.face_ix) if card.faces else []
    return faces[0] if faces else None


def _build_html(
    *,
    title: str,
    description: str,
    canonical: str,
    og_type: str = "website",
    og_image: str | None = None,
    body_h1: str,
    body_text: str | None = None,
    body_eyebrow: str | None = None,
    extra_head: str = "",
) -> str:
    safe_title = escape(title, {'"': "&quot;"})
    safe_description = escape(description, {'"': "&quot;"})
    safe_canonical = escape(canonical, {'"': "&quot;"})
    safe_og_type = escape(og_type, {'"': "&quot;"})

    image_tags = ""
    if og_image:
        safe_image = escape(og_image, {'"': "&quot;"})
        image_tags = (
            f'<meta property="og:image" content="{safe_image}">\n'
            f'<meta name="twitter:image" content="{safe_image}">'
        )
    twitter_card = "summary_large_image" if og_image else "summary"

    body_eyebrow_html = (
        f'<p class="eyebrow">{escape(body_eyebrow)}</p>' if body_eyebrow else ""
    )
    body_text_html = f"<p>{escape(body_text)}</p>" if body_text else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title}</title>
<meta name="description" content="{safe_description}">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{safe_canonical}">
<meta property="og:site_name" content="Oracle Tutor">
<meta property="og:type" content="{safe_og_type}">
<meta property="og:title" content="{safe_title}">
<meta property="og:description" content="{safe_description}">
<meta property="og:url" content="{safe_canonical}">
{image_tags}
<meta name="twitter:card" content="{twitter_card}">
<meta name="twitter:title" content="{safe_title}">
<meta name="twitter:description" content="{safe_description}">
{extra_head}
</head>
<body>
{body_eyebrow_html}
<h1>{escape(body_h1)}</h1>
{body_text_html}
<p><a href="{safe_canonical}">View on Oracle Tutor</a></p>
</body>
</html>"""


def _render_home(origin: str) -> str:
    return _build_html(
        title=f"{_SITE_NAME}: {_TAGLINE}",
        description=_DEFAULT_DESCRIPTION,
        canonical=f"{origin}/",
        og_type="website",
        body_h1=_SITE_NAME,
        body_text=_DEFAULT_DESCRIPTION,
        body_eyebrow=_TAGLINE,
    )


def _render_query(origin: str, query: str) -> str:
    canonical = f"{origin}/?q={quote_plus(query)}"
    title = f'"{query}" | {_SITE_NAME}'
    description = (
        f'Magic: The Gathering cards matching "{query}". '
        f"Semantic search by meaning on {_SITE_NAME}."
    )
    return _build_html(
        title=title,
        description=description,
        canonical=canonical,
        og_type="website",
        body_h1=f'Search: "{query}"',
        body_text=description,
        body_eyebrow=_SITE_NAME,
    )


def _render_card(origin: str, card: Card) -> str:
    face = _primary_face(card)
    name = card.name
    type_line = (face.type_line if face else None) or ""
    oracle_text = (face.oracle_text if face else None) or ""

    title = f"{name} | {_SITE_NAME}"
    description_source = f"{type_line}. {oracle_text}".strip(" .")
    description = (
        _truncate(description_source) if description_source else f"{name} on {_SITE_NAME}."
    )
    canonical = f"{origin}/?card={card.oracle_id}"

    og_image: str | None = None
    if face and face.image_uris:
        og_image = face.image_uris.get("normal") or face.image_uris.get("large")
    if not og_image:
        og_image = _scryfall_image_url(card.scryfall_id)

    json_ld = _card_json_ld(card, face, og_image, canonical, description)

    body_text_lines: list[str] = []
    if type_line:
        body_text_lines.append(type_line)
    if oracle_text:
        body_text_lines.append(oracle_text)
    body_text = "\n\n".join(body_text_lines) if body_text_lines else None

    return _build_html(
        title=title,
        description=description,
        canonical=canonical,
        og_type="article",
        og_image=og_image,
        body_h1=name,
        body_text=body_text,
        body_eyebrow=_SITE_NAME,
        extra_head=f'<script type="application/ld+json">{json_ld}</script>',
    )


def _card_json_ld(
    card: Card,
    face: CardFace | None,
    image: str | None,
    url: str,
    description: str,
) -> str:
    import json

    payload: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "Game",
        "name": card.name,
        "url": url,
        "description": description,
        "isPartOf": {"@type": "VideoGameSeries", "name": "Magic: The Gathering"},
    }
    if image:
        payload["image"] = image
    if face and face.type_line:
        payload["genre"] = face.type_line
    if card.rarity:
        payload["additionalProperty"] = [
            {"@type": "PropertyValue", "name": "rarity", "value": card.rarity}
        ]
    return json.dumps(payload, ensure_ascii=False)


@router.get("/seo/page", response_class=HTMLResponse, include_in_schema=False)
def seo_page(
    card: str | None = Query(None, max_length=64, pattern=r"^[A-Za-z0-9-]+$"),
    q: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    origin = public_app_url() or ""
    headers = {"Cache-Control": "public, max-age=300"}

    if card:
        row = db.execute(
            select(Card).options(joinedload(Card.faces)).where(Card.oracle_id == card)
        ).unique().scalar_one_or_none()
        if row is None:
            return HTMLResponse(_render_home(origin), status_code=404, headers=headers)
        return HTMLResponse(_render_card(origin, row), headers=headers)

    if q:
        return HTMLResponse(_render_query(origin, q.strip()), headers=headers)

    return HTMLResponse(_render_home(origin), headers=headers)
