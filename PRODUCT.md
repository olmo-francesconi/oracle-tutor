# Product

## Register

product

## Users

Magic: The Gathering players and deckbuilders who already know roughly what a card *does* but can't recall the name (or don't know if a card with that effect even exists). They search by meaning — "untap when blocked", "two damage to anything when sacrificed", "exile from graveyard at end of turn" — and expect the right cards back, regardless of how the oracle text is actually phrased.

Context: usually mid-deckbuild, often jumping in and out of similar tools (Scryfall, EDHREC, Moxfield). They're fluent in mana symbols, type lines, and rarity, and don't need the interface to teach them the game. They want speed of recall and confidence in the result set.

## Product Purpose

Oracle Tutor is a semantic search engine over Magic's full card pool. The user types intent; pgvector + a fine-tuned ONNX embedding model returns the cards that match by meaning. Filters (color, CMC, type, rarity, format) refine the set. A pinned card pivots the search to "more like this".

Success looks like: the user types a fuzzy idea, the right card is in the first row of results, and they pivot from there. If they have to fall back to a name-based tool to disambiguate, the product has missed.

## Brand Personality

**Editorial. Confident. Playful.**

Voice: dry, direct, lowercase tagline copy ("find cards by meaning, not keywords"), no marketing puffery. Big uppercase display type for surfaces that matter (titles, card names), monospace for body and oracle text. Hard 2px rules, no soft shadows, no rounded chrome. The page is treated like a magazine spread, not an app shell.

Playfulness lives in the dense oracle-text background that quietly fills the canvas, the `ot-red` accent stripe down the left edge, and the willingness to drop chrome (no Results bar, no card-count tag) when it isn't pulling weight.

## Anti-references

- **Generic SaaS dashboards** (Linear / Stripe / Notion product chrome): sidebars, blue accents, soft shadows, rounded-2xl cards. Oracle Tutor is a typography-led canvas, not a productivity shell.
- **Scryfall / EDHREC**: database-heavy, set-symbol decoration, dense table rows, Wizards-of-the-Coast house styling. The competition's visual language is exactly what this should not feel like.
- **Crypto / fintech maximalism**: neon glows, animated gradients, glassmorphism, decorative backdrop blurs. Motion and color are restrained on purpose.
- **Generic minimalism / Vercel template look**: Inter, gray-on-white, rounded-2xl, evenly-spaced empty space, no rhythm. Restraint here is editorial, not bland.

## Design Principles

1. **Meaning, not keywords.** The UI should constantly signal that this is semantic search, not string match. The homepage editorial layout, the dense oracle-text background, and the "Similar to" pivot all reinforce that the unit of query is *intent*.
2. **Every piece of chrome earns its place.** Remove labels, counts, and frames whenever they're not load-bearing. Recent culls: card frames, set-symbol borders, the results-summary echo bar, the `{n} cards` indicator, the duplicate similarity row in the detail overlay. If a future component can't justify itself, kill it.
3. **Hard rules, fixed sizes.** 2px ink dividers, fixed type sizes, pinned `min-height` on header bars. Stability beats fluid clamps where the user reads the same surface many times in a session.
4. **The card is the content.** Card images render frameless with uniform `rounded-xl`. The grid breathes (always ≥ 2 columns, scales up to 6 on big screens). Detail view is a magazine spread, not a modal cliché.
5. **Editorial canvas, persistent.** The dense oracle-text background lives at the shell level (`SearchShell`), not the home view, so it survives navigation. The `ot-red` left stripe is a brand signature: it should never get covered by content.

## Accessibility & Inclusion

- WCAG 2.2 AA target. The `ot-ink` (#111111) on `ot-bg` (#f0ede6) text pair clears AAA for normal text; `ot-muted` (#7a7670) for eyebrows is borderline AA on smaller sizes — never use it for primary content.
- `prefers-reduced-motion` is respected at every transition site (`motion-reduce:transition-none`). Fade-ins, hovers, the detail overlay's open animation, all gated.
- Focus states are intentional: `:focus-visible` outlines in `ot-red` with 2px offset; the detail overlay implements full focus trap, focus restore, `inert` on the rest of the document, and ESC + backdrop close.
- Mana symbols are decorative font glyphs with paired `aria-label` text on the inline `<span>` so screen readers hear the cost, not the icon class.
- Color is never the only carrier of meaning — filter chips, rarities, and similarity all have text labels.
