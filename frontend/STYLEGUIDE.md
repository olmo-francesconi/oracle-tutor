# Oracle Tutor — Frontend Style Guide

Bauhaus/brutalist design system. Every new UI element must follow these rules.

---

## Colors

| Token | Value | Usage |
|-------|-------|-------|
| `--ot-bg` | `#F0EDE6` | Page background (warm newsprint) |
| `--ot-surface` | `#FFFFFF` | Cards, filter strip, modals |
| `--ot-ink` | `#111111` | Text, borders, filled states |
| `--ot-red` | `#CC1100` | Bauhaus accent — home stripe, filter badge |
| `--ot-yellow` | `#F5C400` | Semantic section divider in dropdown |
| `--ot-muted` | `#7A7670` | Secondary text, labels, counts |
| `--ot-cobalt` | `#0E2150` | Home-page editorial composition only |

No other colors for UI chrome. `--ot-cobalt` is reserved for the home-page art composition, not general-purpose interface accents. No gradients. No opacity tricks for text color — use `#7A7670` for muted.

### Semantic MTG Colors

These colors are approved for card-domain semantics inside filter chips only. Do not reuse them for general chrome, layout accents, or call-to-action styling.

| Token | Value | Usage |
|-------|-------|-------|
| `--ot-mtg-white` | `#C8A96E` | White color identity chip |
| `--ot-mtg-blue` | `#1E5094` | Blue color identity chip |
| `--ot-mtg-black` | `#111111` | Black color identity chip |
| `--ot-mtg-red` | `#CC1100` | Red color identity chip |
| `--ot-mtg-green` | `#2E6840` | Green color identity chip |
| `--ot-mtg-colorless` | `#7A7670` | Colorless chip |
| `--ot-rarity-common` | `#333333` | Common rarity chip |
| `--ot-rarity-uncommon` | `#8499A8` | Uncommon rarity chip |
| `--ot-rarity-rare` | `#C8A96E` | Rare rarity chip |
| `--ot-rarity-mythic` | `#C96428` | Mythic rarity chip |

---

## Typography

| Role | Class | Font | Weight | Usage |
|------|-------|------|--------|-------|
| Display | `font-display` | Big Shoulders Display | 800–900 | Logo, headings, section labels, card names |
| Body / UI | `font-mono` | DM Mono | 400–500 | All other text: inputs, metadata, tags, counts |

- Never use system fonts or Inter.
- Display text is always `uppercase`.
- Body text is always DM Mono — including `<p>`, `<span>`, `<label>`, `<button>` text that isn't a heading.

---

## Borders & Radius

- **All borders:** `border-2 border-[#111111]` — 2px solid ink. No exceptions.
- **Border radius:** `0` everywhere — no `rounded-*` classes on any UI chrome.
- Exception: MTG card images use `borderRadius: '4.5% / 3.21%'` (the physical card shape). This is a named constant `CARD_RADIUS_STYLE` in `CardGrid.tsx`.

---

## Spacing & Layout

- Base unit: 4px (Tailwind default scale).
- Content padding: `px-8 py-5` for main content areas, `px-5` for top bar items.
- Gap between sections: `mb-8`.

---

## Interaction States

- **Hover:** Full background inversion — `hover:bg-[#111111] hover:text-[#F0EDE6]` (or `hover:text-white`).
- **Active / selected:** Same inversion applied statically.
- **Disabled:** `border-[#CCCCCC] text-[#CCCCCC]` — no fill.
- No box-shadow, no blur, no ring on any interactive element.

---

## Page Layout Pattern

Every page (search results, card page) follows this exact structure:

```
┌─────────────────────────────────────────────────────┐  ← 56px, border-b-2
│  Logo (border-r-2)  │  Content area  │  Filter btn  │
├─────────────────────────────────────────────────────┤  ← hidden by default
│  Filter strip (bg-white, border-b-2, collapsible)   │
├─────────────────────────────────────────────────────┤  ← border-b-2
│  Content header (query text OR card detail panel)   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Full-width card grid (flex-1, overflow-y-auto)     │
│                                                     │
└─────────────────────────────────────────────────────┘
```

- No sidebars. Ever.
- `showFloatingFilters={false}` on all `<CardGrid>` — filter state lives in the page.
- Top bar height: always 56px (`style={{ height: 56 }}`).

---

## Components

### Top bar
```tsx
<div className="flex shrink-0 items-stretch border-b-2 border-[#111111]" style={{ height: 56 }}>
  <Link to="/" className="... border-r-2 border-[#111111] font-display ...">Oracle Tutor</Link>
  {/* content area — border-r-2 on right */}
  <button className="... border-l-2 border-[#111111] font-display uppercase ...">Filters</button>
</div>
```

### Filter strip
```tsx
{showFilters && (
  <div className="flex shrink-0 items-center border-b-2 border-[#111111] bg-white px-4">
    <FilterBar filters={filters} onFilterChange={setFilters} variant="inline" />
  </div>
)}
```

### Section headers (in CardGrid)
```tsx
<div className="mb-4 flex items-center gap-3 border-b-2 border-[#111111] pb-3">
  <span className="font-display text-[13px] font-bold uppercase tracking-[0.14em]">Perfect</span>
  <span className="text-[11px] text-[#7A7670]">6</span>
  <div className="h-[2px] flex-1 bg-[#111111]" />  {/* color varies by section */}
</div>
```

Section bar colors: perfect `#111111` · great `#444444` · good `#888888` · poor `#BBBBBB` · default `#DDDDDD`

### Buttons
```tsx
{/* Default */}
<button className="border-2 border-[#111111] px-4 py-2 font-display text-[11px] font-bold uppercase tracking-[0.1em] text-[#111111] transition-colors hover:bg-[#111111] hover:text-white">
  Label
</button>

{/* Active/filled */}
<button className="border-2 border-[#111111] bg-[#111111] px-4 py-2 font-display text-[11px] font-bold uppercase tracking-[0.1em] text-white">
  Label
</button>
```

---

## Design Previews

`frontend/design-previews/home.html` and `results.html` are the canonical visual reference. Open them directly in a browser. When in doubt about a layout decision, check the preview first.
