# Fashion Archive — design language

The interface for a photograph archive. One monospace face, black on white,
greys for everything that is not the thing you came to look at. The
photographs are the only colour on the page; the interface stays out of
their way.

This document is the written half of the system. The other half is live:

- **`/styleguide`** in the running app renders every token and primitive in
  every state, reading values from the stylesheet. Needs no sign-in.
- **`web_ui/src/shared/styles/archive.css`** is the source of truth. Its
  header carries the rules; its `:root` block carries the tokens; the rest
  is the primitives.
- **`web_ui/design/tokens.json`** is the same tokens as W3C Design Tokens
  JSON, generated from the CSS, for import into Figma variables or Tokens
  Studio. Never edited by hand.

Terms: **chrome** is the interface (labels, buttons, headers, status).
**Content** is what the archive holds (a designer, a show, a product, a
note the user wrote).

---

## 1. Principles

1. **Black means selected or active.** Nothing else is black. A page with
   two black things has two selections.
2. **Colour means destructive.** One hue (`danger`), allowed on exactly one
   control: the confirmation of an irreversible delete. Never a hover, a
   badge, or emphasis.
3. **Uppercase + tracking is chrome.** Content is sentence case and
   untracked. This is how the eye separates the interface from the archive
   without a second colour or a second typeface.
4. **Hairlines separate. Nothing casts a shadow.**
5. **Hover is a wash, not a colour.** A 2% black wash, text to black.
6. **No radius.** Corners are square everywhere, including inputs,
   thumbnails and scrollbar thumbs.
7. **Sizes come off the scales.** A stylesheet never writes a literal; the
   build fails if one does.
8. **Weight: 400 text, 600 emphasis, 700 selected.**
9. **Motion is functional.** Three durations. Nothing bounces.
10. **Readable text meets WCAG AA.** Every word is at least 4.5:1 on its
    ground. Every focusable control shows the same 1px black outline under
    keyboard focus.

---

## 2. Tokens

Names are the CSS custom property without the `--ar-` prefix. The same names
appear in `tokens.json` and should be used verbatim as Figma variable names.

### Colour

| Token | Value | Use | Contrast on white |
|---|---|---|---|
| `bg` | `#ffffff` | page ground | — |
| `bg-sub` | `#fafafa` | sidebars, strips, toolbars | — |
| `bg-sunk` | `#f5f5f5` | wells: image placeholders, pressed hover, scrollbar track | — |
| `line` | `#e0e0e0` | hairline rules between regions | 1.3:1 (decorative only) |
| `line-soft` | `#ededed` | rules inside a grouped block | decorative only |
| `ink` | `#000000` | selected, active, typed text | 21:1 |
| `ink-2` | `#666666` | body | 5.7:1 AA |
| `ink-3` | `#767676` | labels, counts, idle controls, placeholders | 4.5:1 AA |
| `ink-4` | `#949494` | disabled text, glyph-only controls, input borders | 3.0:1 — never a word |
| `danger` | `#cc0000` | destructive confirmation only | 5.9:1 AA |
| `wash` | `rgba(0,0,0,.02)` | hover | — |
| `wash-strong` | `rgba(0,0,0,.03)` | selected row | — |
| `scrim` | `rgba(0,0,0,.28)` | behind a panel that has focus | — |
| `shield` | `rgba(0,0,0,.9)` | over a video while it loads | — |

There are exactly three greys for words. That is deliberate: on white, only
`#666` and `#767676` clear AA while staying visibly lighter than black, so a
fourth readable grey does not exist. Hierarchy beyond three levels comes
from size, case and tracking, not from more greys.

### Type

Face: `JetBrains Mono`, falling back to `SF Mono`, `Monaco`, `monospace`.
There is one face; there is no display face and no reading face.

| Token | Size | Role |
|---|---|---|
| `fs-micro` | 9px | counts, timestamps, meta under a name |
| `fs-label` | 10px | section headers, facet labels, tiny controls |
| `fs-ui` | 11px | buttons, inputs, chips, status bar |
| `fs-body` | 12px | list rows, notes, everything readable |
| `fs-heading` | 13px | the name at the top of a panel or album |
| `fs-title` | 24px | the one big thing on a page; empty-state glyphs |

| Token | Value | Role |
|---|---|---|
| `track-tight` | 0.05em | a name that needs a little air |
| `track-ui` | 0.1em | buttons, chips, inputs, status |
| `track-label` | 0.15em | section headers, placeholders, empty states |
| `track-wide` | 0.2em | the wordmark |

| Token | Value | Role |
|---|---|---|
| `lh-none` | 1 | a glyph or a single-line control |
| `lh-ui` | 16px | rows, labels, anything 9–12px |
| `lh-body` | 20px | paragraphs, notes, the heading size |

Weights: `400` text, `600` emphasis inside content, `700` the selected row
or chip. Nothing lighter, nothing heavier.

#### Type roles, composed

| Role | Size | Line | Tracking | Case | Weight | Colour |
|---|---|---|---|---|---|---|
| Section header | label | ui | label | UPPER | 400 | ink-3 |
| Count beside a header | label | ui | label | — | 400 | ink-3 |
| Button / chip / segment | ui | none | ui | UPPER | 400 (700 selected) | ink-3 (ink selected) |
| Input text | ui | none | — | as typed | 400 | ink |
| Input placeholder | ui | none | ui | UPPER | 400 | ink-3 |
| List row (content) | body | ui | — | Sentence | 400 (700 selected) | ink-2 (ink selected) |
| Meta under a row | micro | ui | — | Sentence | 400 | ink-3 |
| Panel / album heading | heading | body | tight | Sentence | 400 | ink |
| Page title | title | body | — | Sentence | 400 | ink |
| Status bar | ui | none | ui | UPPER | 400 (600 active) | ink-3 (ink active) |
| Empty state headline | ui | ui | label | UPPER | 400 | ink-3 |
| Wordmark | heading | none | wide | UPPER | 700 | ink |

### Space

Padding, gap and margin are even pixels off this scale:

`2 4 6 8 10 12 16 20 24 32 48`

plus `1px` for a hairline gap between two segments. No odd numbers. Rows
are `6px 12px`, buttons `8px 16px`, page gutters `24px`, section headers
`14px 12px 10px` (the one exception, kept because the optical balance of the
uppercase label wants it).

### Size

| Token | Value | What |
|---|---|---|
| `sidebar-w` | 280px | every sidebar |
| `topbar-h` | 48px | the top bar |
| `statusbar-h` | 36px | the status bar |
| `hairline` | 1px | every rule and border |
| `marker` | 2px | the left bar on a selected row or chip |

### Motion

| Token | Value | Use |
|---|---|---|
| `fast` | 100ms | colour, hover |
| `base` | 150ms | borders, opacity |
| `slow` | 200ms | a panel sliding or resizing |

Easing is `ease` everywhere. There is no spring, no overshoot, no delay.

---

## 3. Layout

Desktop only. The body does not scroll; each page is a fixed frame and its
regions scroll internally. There are no breakpoints. The minimum useful
viewport is about 1100px wide.

```
┌──────────────────────────────────────────────────────────────┐
│ ARCHIVE      COLLECTIONS  LIBRARY  MY BRANDS         user  ⋯ │  topbar-h 48, bg, line below
├──────────────┬───────────────────────────────────────────────┤
│ sidebar      │ content                                       │
│ bg-sub       │ bg                                            │
│ 280 wide     │                                               │
│ line right   │   the photographs                             │
│              │                                               │
│ section hdr  │                                               │
│ list rows    │                                               │
│ chips        │                                               │
│              │                                               │
│ ┌──────────┐ │                                               │
│ │ recents  │ │                                               │
│ └──────────┘ │                                               │
├──────────────┴───────────────────────────────────────────────┤
│ Acne Studios · Spring 2025 · 12 / 48                  LOADED │  statusbar-h 36, line above
└──────────────────────────────────────────────────────────────┘
```

- **Top bar**: wordmark left, page switch centre-left as text links, user
  and sign-out right. Never grows.
- **Sidebar**: navigation and filters for the current page. Section
  headers, list rows and chips stack; the bottom can hold a drawer
  (recently seen) that opens upward.
- **Content**: the photographs. It has as little chrome as possible: a
  segmented view switch, a thumbnail strip, arrows.
- **Status bar**: where you are, in words. Active segment in `ink` at 600.

A panel that takes focus (album picker, product detail) sits over `scrim`
and is edged with `line`, not a shadow.

---

## 4. Iconography

There is no icon set. Controls are words. Where a glyph is unavoidable it is
a character from the type face, coloured `ink-4` when idle and `ink` when
active, at the size of the text beside it:

| Glyph | Meaning |
|---|---|
| `→` `←` | open / next, back / previous |
| `…` | loading, or more available |
| `☆` `★` | not saved / saved (the star is the only save control) |
| `▾` `▴` `▸` | expand, collapse, disclosure |
| `▶` | play |
| `✕` | close, clear |

A designer adding a glyph picks from this list or extends it here first.
No SVG icons, no icon font.

---

## 5. Components

### Primitives (`.ar-*`, in `archive.css`)

Every primitive is shown in every state on `/styleguide`.

| Primitive | Anatomy | States | Use |
|---|---|---|---|
| `.ar-section-header` + `.count` | uppercase label, optional count right | — | tops a group in a sidebar |
| `.ar-list-item` | row, 2px left marker | idle · hover (wash, ink) · `.selected` (wash-strong, 700, marker) | one item of a navigable list |
| `.ar-chip` | text-only toggle, left marker | idle · hover · `.selected` | modes that stack vertically in a sidebar |
| `.ar-segmented` › `.ar-segment` | hairline-gapped row, black fill on the chosen one | idle · hover (sunk) · `.selected` · `:disabled` | one of N views, side by side |
| `.ar-btn` | bordered uppercase text | idle · hover (ink border) · `.active` (black fill) · `:disabled` · `.ar-btn-danger` · `.ar-btn-block` | any action |
| `.ar-input` / `.ar-select` | ink-4 border, square | idle · `:focus` (ink border) · `::placeholder` | fields |
| `.ar-star` | ☆ / ★ glyph button | idle (ink-4) · hover (ink) · `.on` (ink) · `.sm` | saving; there is no other save control |
| `.ar-status-bar` | 36px strip, line above | `.active` segment | where you are |
| `.ar-empty` / `.ar-loading` | centred uppercase headline + line | — | nothing here yet / still arriving |
| `.ar-scroll` | 6px square thumb, no track | hover (ink-4) | any scrolling region |
| `.ar-page` / `.ar-content` / `.ar-sidebar` | the frame in §3 | — | every page |

Accessibility on the primitives: toggles carry `aria-pressed`; the star has
an `aria-label`; the segmented group is `role="group"` with a label; every
control is a real `<button>` or `<input>` so it is reachable by Tab and
shows the global focus outline.

### Feature components (by stylesheet)

Each page owns its stylesheet and a class prefix. These are the components
inside them a designer will meet, so the map from screen to code is one
lookup.

| Page | Prefix | Components |
|---|---|---|
| High Fashion (the archive) | `hf2-` | designer nav, collections list, search with results, facet filters, segmented mode, recently-seen drawer, single-image viewer (frame, thumb strip, arrows, progress bar), grid view, video frame with resize bar, status bar |
| Library | `lib-`, `fav-` | kinds list, album list, saved-looks single/grid, saved shows list |
| Album | `alb-` | album grid tiles, freeform canvas (`AlbumCanvas`), layout toggle, filter, actions |
| My Brands | `brand-`, `nav-`, `product-`, `detail-`, `carousel-` | brand nav, product grid tiles, product detail panel with image carousel |
| Shared view | `shv-` | public, read-only album or look |
| Top bar | `topbar-` | wordmark, page switch, user, sign-out |
| Album picker | `alp-` | the panel that opens from a star |
| Share button | `share-` | mints a link, copies it |
| Dev | `dev-` | the machine room; not user-facing |

Naming rule for new work: a feature class is `<prefix>-<part>`; anything
used on more than one page is promoted to `.ar-*` in `archive.css` and
added to `/styleguide`.

---

## 6. Content rules

- **Chrome is uppercase; content is not.** "DESIGNERS" is a header. "Comme
  des Garçons" is a designer.
- **Images are not numbered as looks.** A photograph is "12 / 48", not
  "Look 12". The archive does not know which image is which look.
- **Counts are plain numbers with a thin-space thousands separator** where
  the font allows it: `1 204`.
- **Empty states say what to do**, in one short line under the headline.
- **Destructive actions are named for what they destroy**: "Remove from
  library", never "Delete".
- **Times are relative when recent** ("2h ago"), absolute otherwise.

---

## 7. Accessibility

- Every word ≥ 4.5:1 on its ground (`ink-2`, `ink-3` on `bg`/`bg-sub`).
- `ink-4` is reserved for disabled text (exempt) and glyphs/borders (3:1
  floor for non-text). It is never used for a word.
- Keyboard focus: `:focus-visible` gives every control a 1px `ink` outline,
  inset. Mouse focus shows nothing.
- Toggles use `aria-pressed`; glyph buttons have `aria-label`; decorative
  glyphs are `aria-hidden`.
- Hit targets are the full row or the full button; nothing is smaller than
  the 22px star box.
- Motion is short enough that a reduced-motion preference changes nothing
  perceptible; there are no animations that loop except the loading pulse.

---

## 8. Working with the system

**Designer, in Figma**

1. Import `web_ui/design/tokens.json` as variables (Figma's variable
   import, or Tokens Studio). Keep the names.
2. Design with those variables only. If you need a value that isn't a
   token, that is a proposal: name it, say what it is for, and it gets added
   to `archive.css` first, then exported.
3. `/styleguide` is the reference for what each primitive looks like in the
   running product. Screens are composed from primitives plus the page's
   feature components listed in §5.

**Developer, in code**

1. Add or change a token in `archive.css` `:root`, with its trailing
   comment (that comment becomes the token's description in the JSON).
2. `npm run tokens:export` and commit `design/tokens.json`.
3. Use tokens in every stylesheet. `npm run check:tokens` (and every build)
   refuses a hex, a px font-size, a raw tracking, duration, line-height,
   weight outside 400/600/700, any radius, any shadow, or an odd padding.
4. Anything used on two pages becomes an `.ar-*` primitive and gets a
   section on `/styleguide`.

---

## 9. Known gaps and open decisions

These are known, not forgotten. A designer joining should treat them as the
first things to decide.

- **Desktop only.** No breakpoints, body does not scroll. A phone layout is
  a separate design, not a media query.
- **No dark mode.** The tokens make one possible (swap the `:root` block);
  nothing has been designed for it.
- **Glyphs as icons.** Works at this scale; would not survive a larger
  control vocabulary.
- **Three readable greys.** See §2. If more hierarchy is needed, it comes
  from type, not colour.
- **Naming families.** High Fashion's `hf2-` prefix carries 184 selectors;
  it predates the primitives and has not been split into components yet.
- **One face.** `JetBrains Mono` for everything, including 24px titles.
  Whether a proportional face belongs on titles is an open aesthetic call.
