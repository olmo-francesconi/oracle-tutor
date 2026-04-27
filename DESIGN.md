---
name: Oracle Tutor
description: Editorial semantic-search canvas for Magic, the Gathering.
colors:
  newsprint-cream: "#f0ede6"
  pure-surface: "#ffffff"
  pressed-ink: "#111111"
  editors-red: "#cc1100"
  faded-mark: "#7a7670"
  newsprint-rule: "#d8d2c8"
  highlighter: "#f5c400"
typography:
  display:
    fontFamily: "Big Shoulders Display, sans-serif"
    fontSize: "2.4rem"
    fontWeight: 900
    lineHeight: 0.9
    letterSpacing: "-0.02em"
  hero:
    fontFamily: "Big Shoulders Display, sans-serif"
    fontSize: "clamp(4.5rem, 11vw, 7rem)"
    fontWeight: 900
    lineHeight: 0.86
    letterSpacing: "-0.03em"
  card-name:
    fontFamily: "Big Shoulders Display, sans-serif"
    fontSize: "clamp(2rem, 3.4vw, 3rem)"
    fontWeight: 900
    lineHeight: 0.9
    letterSpacing: "-0.025em"
  body:
    fontFamily: "DM Mono, monospace"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "DM Mono, monospace"
    fontSize: "0.6875rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "0.18em"
rounded:
  none: "0"
  card: "0.75rem"
spacing:
  rule-thin: "1px"
  rule-thick: "2px"
  inset-tight: "8px"
  inset-default: "18px"
  inset-loose: "28px"
components:
  button-primary:
    backgroundColor: "{colors.pressed-ink}"
    textColor: "{colors.newsprint-cream}"
    rounded: "{rounded.none}"
    padding: "16px 24px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.pressed-ink}"
    rounded: "{rounded.none}"
    padding: "12px 18px"
  button-ghost-hover:
    backgroundColor: "{colors.pressed-ink}"
    textColor: "{colors.newsprint-cream}"
  button-close:
    backgroundColor: "transparent"
    textColor: "{colors.pressed-ink}"
    rounded: "{rounded.none}"
    width: "58px"
    height: "58px"
  button-close-hover:
    backgroundColor: "{colors.editors-red}"
    textColor: "#ffffff"
  chip-flip:
    backgroundColor: "{colors.newsprint-cream}"
    textColor: "{colors.pressed-ink}"
    rounded: "{rounded.none}"
    padding: "8px 12px"
  chip-flip-hover:
    backgroundColor: "{colors.pressed-ink}"
    textColor: "{colors.newsprint-cream}"
  card-image:
    backgroundColor: "{colors.newsprint-rule}"
    rounded: "{rounded.card}"
  eyebrow-label:
    textColor: "{colors.faded-mark}"
    typography: "{typography.label}"
  divider-rule:
    backgroundColor: "{colors.pressed-ink}"
    height: "2px"
---

# Design System: Oracle Tutor

## 1. Overview

**Creative North Star: "The Oracle Spread"**

Oracle Tutor is laid out like a magazine spread, not an app shell. Every page is a composition: hard 2px ink rules section the canvas, big uppercase display type carries titles, monospace carries oracle text and labels. The dense oracle-text background lives behind the entire shell, drifting at 8.8% opacity like newsprint pulled close to the eye. The single accent, an editor's red stripe down the left edge of the viewport, is the brand mark that never moves.

The personality is editorial, confident, and quietly playful. Restraint is the dominant gesture, but the system permits theatrics where they earn it: the homepage hero swells to 7rem, the detail overlay opens into a two-plate spread with the card framed against a hush of `newsprint-rule` gray, and the result grid drops every frame so the cards themselves are the content. The system rejects SaaS chrome, Scryfall's database styling, crypto/fintech ornament, and the gray-on-white Vercel-template default in equal measure.

**Key Characteristics:**
- 2px ink rules, never 1px hairlines or soft shadows
- Display type for titles, monospace for body and labels, no third family
- Restrained color: tinted neutrals + one accent, used at < 5% of any surface
- Frameless card images at uniform `rounded-xl` (0.75rem) corners
- A persistent dense-text background and a persistent left red stripe across all routes
- No drop shadows except a single low-key shadow under the detail overlay panel

## 2. Colors: The Newsprint Palette

A warm, off-white press sheet inked deep, pulled in a single editor's red.

### Primary
- **Editor's Red** (#cc1100): The single accent. Reserved for the persistent 6px left stripe, hover state on the close button (full red field with white glyph), and the title hover on pinned-card mode. Never used for body text, never used as a fill on more than one element at a time.

### Neutral
- **Newsprint Cream** (#f0ede6): The page. The `body` background. Every section that doesn't have its own purpose lands on this color.
- **Pressed Ink** (#111111): All primary text, all 2px structural rules, the dominant button fill. The system's gravity. Tinted off black, never `#000`.
- **Pure Surface** (#ffffff): Used sparingly for the floating search box editor and a handful of input fields. Not a default surface, a pulled inset.
- **Faded Mark** (#7a7670): Eyebrow labels, secondary captions, "Find similar" sub-text. The voice of a margin note.
- **Newsprint Rule** (#d8d2c8): The 1px secondary divider inside metadata stacks, the `bg-ot-line/40` plate behind the detail-overlay card image, loading-skeleton fills.

### Tertiary
- **Highlighter** (#f5c400): Held in reserve for future emphasis. Not currently in use on the public surface.

### Named Rules

**The One Stripe Rule.** The 6px `editors-red` left stripe is sacred. It paints over every shell, never collides with content, and is the only place red appears at full bleed. Anywhere else, red is ≤ 1% of the visible surface (a hover state, a close button's filled hover field, a focus-visible outline).

**The Two-Color Floor.** A composition is finished when it reads in `pressed-ink` and `newsprint-cream` alone. Gray (`faded-mark`, `newsprint-rule`) is for the second pass. Red is for the third pass at most. If the design only works with all three, it's overworked.

## 3. Typography

**Display Font:** Big Shoulders Display (with `sans-serif` fallback)
**Body / Label Font:** DM Mono (with `monospace` fallback)
**No third family.**

**Character:** Big Shoulders Display is a tight, condensed grotesque drawn for transit signage. It carries every uppercase title, card name, and CTA at weight 900. DM Mono is a humanist monospace with relaxed apertures; it does the writing. The pairing is editorial without being ornamental, technical without being clinical.

### Hierarchy

- **Hero** (900, `clamp(4.5rem, 11vw, 7rem)`, line-height 0.86, letter-spacing -0.03em, uppercase): Reserved for the homepage `Oracle Tutor` mark. Two stacked words on two lines. Nowhere else.
- **Display** (900, `2.4rem` fixed, line-height 0.9, letter-spacing -0.02em, uppercase): Pinned-card title in the results header. Fixed size, never fluid: stability beats responsiveness on a surface the user reads dozens of times a session.
- **Card Name** (900, `clamp(2rem, 3.4vw, 3rem)`, line-height 0.9, letter-spacing -0.025em, uppercase): The card detail overlay's primary heading. Fluid because the overlay is a one-off magazine plate, not a dense surface.
- **Body** (400, `0.95rem`, line-height 1.65): Oracle text in the detail overlay and any prose. Always monospace, never display.
- **Label / Eyebrow** (500, `0.6875rem`, letter-spacing 0.18em, uppercase, `faded-mark`): Section eyebrows ("Card detail", "Similar to", "Mana value"). Carried by the `.eyebrow` class.
- **Metadata Value** (900 display, `1.05rem`, line-height 1, letter-spacing -0.01em, uppercase): The right-aligned value in the detail overlay's metadata definition list. Display type at small size for confident catalog entries.

### Named Rules

**The Display-Stays-Out-Of-Body Rule.** Big Shoulders Display never sets paragraphs. If the text is more than ~5 words, it's body, and body is monospace.

**The Uppercase-Is-Structural Rule.** Every uppercase string is structural (a title, a label, a button). Never decorative. Lowercase belongs to taglines and prose, exclusively.

**The No-Fluid-Title Rule.** The pinned-card results title is fixed at 2.4rem because the user lands on it repeatedly across a session and a fluid clamp made the surface feel unstable. Hero and card-name fluid clamps are tolerated only where the surface is one-shot.

## 4. Elevation

The system is **flat by default**. Depth is conveyed by 2px `pressed-ink` rules that hard-section the canvas, by hue contrast between `newsprint-cream` and `pure-surface`, and by the dense-text background sitting visibly behind every shell. Shadows are nearly absent.

### Shadow Vocabulary

- **Detail Overlay Plate** (`box-shadow: 0 36px 80px -30px rgba(17,17,17,0.55)`): The single large shadow in the system, anchoring the detail overlay panel against the dimmed scrim. Generous Y-offset, deep blur, no spread, low alpha. Reads as light, not as floating.
- **Detail Card Drop** (`box-shadow: 0 22px 40px -26px rgba(17,17,17,0.45)`): The smaller drop under the card image inside the detail overlay's image plate. Same dialect, smaller voice.

### Named Rules

**The Flat-By-Default Rule.** Surfaces are flat at rest. Card frames are forbidden. Soft shadows are forbidden. The only allowed shadow is the detail-overlay pair above, and they exist because the overlay is the only surface that floats.

**The Rule-Over-Shadow Rule.** Where a SaaS dashboard would draw a 1px gray hairline and add a soft shadow to imply depth, this system draws a 2px `pressed-ink` rule and stops. Hard contrast replaces softness everywhere.

## 5. Components

### Buttons

- **Shape:** Square corners (`rounded.none = 0`). Never rounded. Buttons are typeset blocks, not pills.
- **Primary (filled):** `pressed-ink` field, `newsprint-cream` text, padding 16px / 24px, display type weight 900 uppercase, letter-spacing 0.04em. Hover: stays.
- **Ghost (default):** transparent fill, `pressed-ink` text, 2px `pressed-ink` border. Hover **inverts** to `pressed-ink` field with `newsprint-cream` text. The inversion is the entire interaction language — no tint shift, no glow.
- **Close (overlay X):** 58px square, transparent fill at rest, `pressed-ink` glyph, 2px `pressed-ink` left border separating it from the header. Hover fills with `editors-red`, glyph turns white. The only place the system uses red as a fill.
- **Chip (flip control, find-similar inline):** 2px `pressed-ink` border, `newsprint-cream` fill, label-class typography, padding 8px / 12px. Same invert-on-hover language as ghost buttons.

### Card Images

- **Frameless.** No border, no card frame, no MTG card-back styling.
- **Corners:** uniform `rounded-xl` (0.75rem) on all four sides. The same radius across the result grid, the detail overlay, and the loading skeleton. There is no other radius in the system.
- **Background plate (under fallback):** `newsprint-rule` (#d8d2c8) at 40% opacity inside the detail overlay's image cell only. Result grid images sit directly on the page.
- **Loading state:** the image starts at `opacity-0` and fades to `opacity-100` over 500ms `cubic-bezier(0.25, 1, 0.5, 1)` on the `onLoad` event. The similarity caption beneath the image is gated on the same load event so they enter together.

### Result Grid

- **Always ≥ 2 columns.** Fixed breakpoint progression: 2 → 3 (`sm` 35rem) → 4 (`md` 47.5rem) → 5 (`lg` 65rem) → 6 (1500px+). No `auto-fill` or `auto-fit` minmax, because integer column jumps from continuous resizing felt unstable.
- **Gap:** `gap-4` (1rem). Cards breathe; they do not crowd.
- **Caption:** monospace label class, `faded-mark` color, hover transitions to `editors-red`.

### Search Box

- **Pulled inset.** The search editor is the rare place the system uses `pure-surface` (#ffffff) as a background, and only when open. Closed, it sits transparent on the parent surface.
- **Home variant** carries a 6px gradient stripe of `editors-red` at 10% alpha down its left edge as a continuation of the page-level red stripe. Topbar variant doesn't.
- **Caret + placeholder** in `faded-mark`. Typed text in `pressed-ink`, monospace.

### Filter Bar

- **Bar shape:** A horizontal section with 2px `pressed-ink` top and bottom rules, `newsprint-cream` fill. Sits sticky beneath the topbar.
- **Chips:** ghost-button language. Active chips use the inverted state (`pressed-ink` fill, `newsprint-cream` text). No badge dots, no checkmarks; the inversion IS the selected indicator.

### Detail Overlay

- **Backdrop:** `pressed-ink` at 65% alpha, no blur. The dense-text background behind it stays visible at reduced contrast — this is the point. Glassmorphism is forbidden everywhere except where it would obviously help, and it does not help here.
- **Panel:** `newsprint-cream` field, 2px `pressed-ink` border, `max-w-[1080px]`, max-height 90vh on desktop, full-screen with no border on mobile. The only place a shadow lives.
- **Layout:** Two-plate magazine spread on desktop (image plate on the left, type stack on the right, divided by a 2px vertical rule). Single-column document on mobile, with the header bar `sticky top-0`.
- **Header strip:** 58px tall, eyebrow + display sub-line on the left, 58px close button on the right separated by a 2px vertical rule. Same vocabulary as the topbar in `ResultsView`.
- **Metadata list:** `<dl>` with 1px `newsprint-rule` dividers between rows. Eyebrow label on the left, display-type value right-aligned. No nested cards, no chip clusters.

### Dense Oracle-Text Background

- **The signature pattern.** Mounted at the `SearchShell` level so it persists across home and results routes.
- **Placement:** `position: fixed`, full viewport behind everything, behind the 6px red left stripe.
- **Type:** DM Mono at sub-readable size (computed from viewport to fill ~64 lines), `pressed-ink` at **8.8% opacity**, justified word-break. Pulls real oracle texts from `/oracle-samples` and rotates every 10 minutes.
- **Refresh:** controlled by `OT_ORACLE_POOL_REFRESH_SECONDS`. Should never be loud; the moment a user notices it as text they want to read, it has failed.

## 6. Do's and Don'ts

### Do:

- **Do** use 2px `pressed-ink` (#111111) rules to section the canvas. Hard rules are the entire elevation language.
- **Do** keep the 6px `editors-red` (#cc1100) left stripe unbroken across every route. It's the brand mark.
- **Do** let the dense oracle-text background show through gaps in the layout. The result grid's gaps are intentionally background-transparent.
- **Do** invert ghost buttons on hover to `pressed-ink` fill / `newsprint-cream` text. That single language carries every interactive element.
- **Do** drop chrome that doesn't pull weight: card frames, card-count tags, redundant "Results" titles for free-text searches, set-symbol decorations. If a label restates a heading, kill it.
- **Do** use `.eyebrow` class for every secondary label (`faded-mark`, 0.6875rem, letter-spacing 0.18em, uppercase). Labels never freelance their own type.
- **Do** gate every transition on `motion-reduce:transition-none`. Reduced motion is non-negotiable.
- **Do** pin header bars at fixed `min-height` (e.g. 112px on the results summary, 58px on the topbar). Do not let header heights breathe with content.

### Don't:

- **Don't** ship Linear / Stripe / Notion product chrome: sidebars, soft drop shadows, blue accents, `rounded-2xl` cards, gradient buttons. This is the SaaS-dashboard anti-reference from PRODUCT.md, by name.
- **Don't** ape Scryfall or EDHREC: dense data tables, set-symbol decorations, Wizards-of-the-Coast house typography, mana-symbol clutter outside legitimate cost rendering. The competition's visual language is the explicit anti-reference.
- **Don't** introduce neon glows, animated gradients, glassmorphism, or backdrop blurs as decoration. Crypto / fintech maximalism is forbidden.
- **Don't** retreat to Inter + gray-on-white + `rounded-2xl` + evenly-spaced empty space. Generic minimalism is the silent failure mode.
- **Don't** put display type on body copy. Big Shoulders Display never sets paragraphs.
- **Don't** introduce a third type family. Two families, no exceptions.
- **Don't** use `border-left` or `border-right` greater than 1px as a colored stripe on a card or list item. Side-stripe borders are banned. The single 6px `editors-red` left stripe is the page-level signature, not a component pattern.
- **Don't** use `#000` or `#fff` directly. `pressed-ink` (#111111) and `newsprint-cream` (#f0ede6) are the floors and the ceilings.
- **Don't** add `box-shadow` to anything outside the detail overlay's two declared shadows. Hard rules replace soft shadows everywhere else.
- **Don't** make titles or grid columns fluid where they're read repeatedly. The pinned-card results title is fixed at 2.4rem on purpose; the result grid uses fixed integer breakpoints, not `auto-fill`.
- **Don't** open a modal as the first thought. The detail overlay exists because it's the right affordance for a magazine-style detail spread, not because modals are easy. New surfaces should exhaust inline / progressive options before going modal.
