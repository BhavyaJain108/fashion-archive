# Favourites and My Brands: brutalist-white design language

Date: 2026-09-11
Status: implemented 2026-09-11

## Problem

`HighFashionV2` was moved to a new design language — brutalist white, monospace,
hairline rules, monochrome. Favourites and My Brands were not. They still render
the original macOS-glass language: VT323 pixel type at 24–27px, `#f5f5f7`
grounds, `backdrop-filter` blur, 4–6px corner radii, and blue `#007aff`
selection.

The gap is not only inside the two panels. `App.js` renders the old `MenuBar`
plus a VT323 scrolling marquee title bar for every page *except* high-fashion,
so the top 75px of both pages is old-language chrome regardless of what happens
below it.

### The two languages

| | Old (Favourites, My Brands) | New (High Fashion) |
|---|---|---|
| Font | VT323 pixel, 24–27px | JetBrains Mono, 10–12px |
| Ground | `#f5f5f7` + glass blur | `#ffffff` / `#fafafa` sidebar |
| Edges | `border-radius` 4–6px | zero radius, `1px #e0e0e0` |
| Selection | blue `#007aff` tint | black: bold + 2px left border + 3% wash |
| Buttons | blue/red filled, rounded | hairline box, black fill when active |
| Section labels | sentence case, large | 10px uppercase, `0.15em` tracking |
| Scrollbars | 8px, `rgba(0,0,0,.2)`, radius 4px | 4–6px, `#ddd`, square |

## Scope

In scope:

- `FavouritesPanel` — rebuilt to the High Fashion layout anatomy.
- `MyBrandsPanel` — restyled; its structure already matches.
- `ProductDetailPanel` — reached by clicking a product in My Brands.
- The `modern-modal-*` / `modern-button-*` / `modern-input` / `modern-error`
  family — My Brands' add-brand and remove-confirm dialogs.
- `App.js` — chrome swap and the prop changes it forces.
- New `src/styles/archive.css` — the shared language.

Out of scope: `HighFashionV2.css` is not refactored. `MenuBar.js` is not edited
or deleted, only left unrendered. `MacModal.js` is not touched — it has no
consumers at all (nothing in `src/` imports it), so it is dead code and
restyling it would be work with no visible effect.

## Decisions

Three decisions were settled before design, each with alternatives considered.

### 1. Top chrome: swap to the shared TopBar

Both pages render the same `TopBar` as High Fashion, and `App.js` stops drawing
`MenuBar` + marquee for them.

Rejected: restyling only the page bodies (leaves 75px of pixel-font chrome, so
the pages still read as half-converted); restyling `MenuBar` itself into the new
language (leaves two parallel chrome components to maintain, and High Fashion
would still differ from the rest).

Consequence: MenuBar's controls must be re-homed or dropped. See "What is lost".

### 2. Favourites layout: full High Fashion anatomy

Favourites today is a fixed 50/50 split — thumbnail grid left, large image plus
a metadata card right — with no sidebar and no view toggle. It is rebuilt as
280px sidebar + main area + `GRID`/`SINGLE` toggle + thumb strip + status bar.

Rejected: restyling the 50/50 split in place (smaller and lower risk, but
Favourites would stay a different shape from the High Fashion viewer); a middle
option with a sidebar but no grid/single toggle.

### 3. Colour: monochrome, one red reserved

Everything becomes black / white / grey. Red survives in exactly one role:
genuinely destructive confirmation. The value is `#cc0000`, already present in
`HighFashionV2.css` for the video error state, so no new colour enters the
system.

Rejected: strictly monochrome with no exceptions (brand removal discards scraped
data, and deserves a visual warning); keeping blue Add / red Remove / red Sale
as-is (the two pages would not match High Fashion's restraint).

## Architecture

### `src/styles/archive.css` (new)

One file holds the language. Tokens:

```
--ar-bg        #ffffff   page ground
--ar-bg-sub    #fafafa   sidebar, strips, toolbars
--ar-line      #e0e0e0   hairline rules
--ar-line-soft #ededed   rules inside a grouped block
--ar-ink       #000000   selected / active text
--ar-ink-2     #666666   body text
--ar-ink-3     #999999   labels, idle controls
--ar-ink-4     #cccccc   empty states, counts, disabled
--ar-danger    #cc0000   destructive confirmation only
--ar-font      'JetBrains Mono', 'SF Mono', 'Monaco', monospace
```

Primitives, each lifted from an existing `HighFashionV2.css` rule so the two
pages cannot drift from High Fashion visually:

- `.ar-page` — column flex, `100vh`, white ground, mono 12px `--ar-ink-2`.
- `.ar-sidebar` — 280px fixed, `--ar-bg-sub`, right hairline.
- `.ar-section-header` — 10px, uppercase, `0.15em` tracking, `--ar-ink-3`.
- `.ar-list-item` — 12px, `6px 12px`, 2px transparent left border; on hover
  `--ar-ink` over `rgba(0,0,0,0.02)`; when selected, black left border, bold,
  `rgba(0,0,0,0.03)`. ("2% wash" and "3% wash" below mean these two values.)
- `.ar-btn` — hairline box, 11px uppercase `0.1em`, `--ar-ink-3`; border and
  text go black on hover; black fill with white text when active.
- `.ar-btn-danger` — as `.ar-btn`, but border and text go `--ar-danger`.
- `.ar-input` — square, hairline, 11px mono; border goes black on focus.
- `.ar-toolbar` — sticky, `--ar-bg`, bottom hairline.
- `.ar-status-bar` — fixed, 36px, top hairline, 11px `--ar-ink-3`, space-between.
- `.ar-scroll` — 4–6px square scrollbar, `#dddddd` thumb, transparent track.

Tokens are defined once here. `HighFashionV2.css` keeps its literal hexes; the
values are identical, so the pages agree. Migrating High Fashion onto the tokens
is deliberately left for later, to keep the one working page out of this change.

### `FavouritesPanel`

Rebuilt. Structure top to bottom:

- `TopBar`, same props as High Fashion passes it.
- 280px sidebar:
  - A two-chip row at the top — `RECENT` / `BY COLLECTION`. This is where
    MenuBar's View menu (`view-all`, `by-collection`) goes. Styled as
    `.hf2-filter-items.wrap .hf2-chip`.
  - A `COLLECTIONS` header with a count, then the list. Each row is
    `NN` + designer on one line + season on a second, matching
    `.hf2-collection-item`'s `num` / `name` / `sub` structure — the qualifier
    gets its own line rather than being truncated off a shared one.
- Main area:
  - `[GRID][SINGLE]` toggle at top right, as `.hf2-view-toggle`.
  - Grid view: `auto-fill minmax(180px, 1fr)`, 3/4 aspect tiles, look number
    beneath, black outline when selected.
  - Single view: large image, an info line carrying `LOOK NN` against
    `n of total`, a horizontal thumb strip (44×60 thumbs, active one black
    outlined), and prev/next arrows.
  - `REMOVE` moves out of the red pill into the single-view info line as an
    `.ar-btn` that goes `--ar-danger` on hover.
- Status bar fixed at `left: 280px`: `DESIGNER / SEASON` left, `LOOK n / total`
  right.
- Empty state: centred 11px `--ar-ink-4` type — `NO FAVOURITES` over the
  existing instruction line. The 48px 🤍 and its bordered card go.
- Loading state: centred 11px `--ar-ink-4`.

### `MyBrandsPanel`

Restyled only; it is already 280px sidebar + scrolling gallery.

- Container: `height: calc(100vh - 75px)` + `margin-top: 75px` becomes a `100vh`
  column holding `TopBar` and then the content row.
- Sidebar: glass blur removed, flat `--ar-bg-sub` + hairline. Brand names go
  from 27px VT323 to 12px uppercase letterspaced, black and bold when expanded,
  `--ar-ink-3` idle. `loading...` becomes `SCRAPING`. Category rows adopt
  `.ar-list-item`, so selection is the black left border rather than the blue
  wash. `nav-count` goes 11px `--ar-ink-4`. Expand carets stay `▾ ▸` at 9px
  `--ar-ink-4`.
- Footer: `+ ADD BRAND` and `REMOVE` become full-width stacked `.ar-btn`s.
  `REMOVE` takes `.ar-btn-danger` only while arm-mode is active.
  `selected-for-removal` keeps its strikethrough, in `--ar-danger`, over a 3%
  black wash; the pink fill goes.
- Toolbar: search input and sort select become `.ar-input`; focus border is
  black, not blue. The dropdown goes square and hairline with no shadow; its
  `highlighted` row uses the 3% wash plus black left border.
- Product grid: `repeat(4, 1fr)` becomes `auto-fill minmax(180px, 1fr)`. This
  matches High Fashion's grid and stops four columns from crushing on a narrow
  window.
- Card text: centred `clamp(16px, …, 24px)` becomes left-aligned 11px — brand
  uppercase letterspaced `--ar-ink-3`, name `--ar-ink`, price `--ar-ink`. The
  existing black `outline` on the selected card is already right and stays.
- Badges, all 9px uppercase `0.1em`: `SALE` black fill on white text;
  `SOLD OUT` and `IN STOCK` hairline outline in `--ar-ink-2`; `MISSING IMAGE`
  hairline in `--ar-danger`.
- Sizes: `.tile-size` 9px hairline; `.gone` strikethrough in `--ar-ink-4`;
  `.low` marked in `--ar-ink-2` rather than by colour.

### `ProductDetailPanel` and the `modern-modal` dialogs

Both are reached from My Brands, so leaving them would make the page visibly
half-converted.

- `ProductDetailPanel`: hairline `border-left`, square corners, mono type.
  `detail-resize-handle` hover goes black instead of blue.
- The add-brand and remove-confirm dialogs use the `modern-modal-*` family, and
  `MyBrandsPanel` is its only consumer, so those rules move wholesale out of
  `global.css` into `MyBrandsPanel.css` and are rewritten there: the overlay
  keeps a dimming scrim but drops `backdrop-filter`; the dialog loses its 12px
  radius, glass fill and large shadow for a flat white box with a hairline
  border; `modern-modal-title` goes from 30px to 11px uppercase `0.15em`;
  `modern-input` becomes `.ar-input`; `modern-button-primary` becomes a black
  fill, `modern-button-secondary` a hairline box, `modern-button-danger` an
  `.ar-btn-danger`; `modern-error` drops its pink fill and radius for a hairline
  `--ar-danger` border with `--ar-danger` text.

### `App.js`

- Stops rendering `MenuBar` and the marquee title bar for `favourites` and
  `my-brands`. With all three pages converted, that block renders for no page
  and is removed along with the marquee markup.
- Passes `currentPage`, `onPageSwitch`, `currentUser` and `onLogout` to both
  panels, as it already does to `HighFashionV2`.
- `currentView` loses its last consumer. MenuBar was the only writer;
  `MyBrandsPanel` never read it (it is declared `function MyBrandsPanel()`, with
  no props). So the state moves into `FavouritesPanel` as local `groupMode`, and
  the `currentView` prop and `handleViewChange` are deleted.

## What is lost

MenuBar's Tools menu: the Research toggle, Video Test and About dialogs.

`handleResearchToggle`, `handleVideoTest` and the About panel are wired only
inside `MenuBar.js` — nothing else in `src/` references them — and they are
already unreachable from the high-fashion page, which hides MenuBar entirely.

`MenuBar.js` is therefore left in the tree, its own contents untouched. Nothing
is deleted, and the three tools can be re-homed into `TopBar` later if they turn
out to be wanted.

`App.js` does drop its `import MenuBar` along with the render block. An unused
import would trip `no-unused-vars` under the Create React App ESLint config, and
verification requires a clean build with no new warnings.

Also dead, and dead already: the View menu's `all-brands` / `brand-products`
entries, which `MyBrandsPanel` has never read.

## What does not change

Every API call, response shape, state shape and event handler, apart from the
two prop moves above. No behaviour in `services/api.js` is touched. Existing
`try`/`catch` and `console.error` paths stay as they are. Image `onError`
fallbacks stay, with the fallback ground changing from `#f0f0f0` to `#f5f5f5` to
match `.hf2-grid-image-wrapper`.

This is a presentation change.

## Verification

There is no JavaScript test suite. `tests/` holds Python only — `api`, `db`,
`unit` — and no `*.test.js` file exists anywhere outside `node_modules`. So:

1. `npm run build` must compile clean, with no new warnings.
2. Run the app and open each of the three pages in turn, checking Favourites and
   My Brands against High Fashion for: type scale and family, ground and
   hairline colours, selection treatment, corner radius, scrollbar weight.
3. Confirm the behaviour that moved still works: Favourites' `RECENT` /
   `BY COLLECTION` switch, favourite removal, My Brands' add and remove flows,
   category selection, search and sort.
4. Confirm no page still renders VT323 or a blue selection.

## Risks

- Rebuilding Favourites is the largest piece of work and the only place where
  behaviour changes shape. The grid/single distinction is new to the page; its
  existing single-image view becomes the `SINGLE` mode.
- Removing the marquee chrome from `App.js` touches the shared shell. A mistake
  there affects all three pages, including the working one.
- `global.css` is 1882 lines and shared, so deletion has to be selective:

  - The `my-brands`, `brand-*`, `nav-*`, `product-*`, `search-*`, `tile-*`,
    `add-brand` / `remove-brand`, `detail-*` and `modern-*` rules have exactly
    one consumer between them, `MyBrandsPanel`, and are removed as their
    replacements land in `MyBrandsPanel.css`. That includes the whole
    `modern-modal` family at `global.css:690-800` and `modern-button-danger` at
    `1030-1040`.
  - The `mac-*`, `gallery-*` and `columns-container` rules Favourites currently
    uses are **kept**. `gallery-item`, `gallery-image-container` and
    `gallery-look-label` are also used by `ImageViewerPanel`; `mac-panel` and
    `mac-button` are also used by `CollectionsPanel`, `SeasonsPanel`,
    `VideoModal`, `ImageViewerPanel` and `MenuBar`. Favourites simply stops
    referencing them.
  - `marquee-track` / `marquee-item` have `App.js` as their only consumer and go
    with the marquee markup.

  Note for whoever picks this up next, not a task here: `SeasonsPanel`,
  `CollectionsPanel` and `ImageViewerPanel` are imported by `App.js` but never
  rendered — the render tree only reaches `HighFashionV2`, `FavouritesPanel`,
  `MyBrandsPanel`, `VideoWindow` and `AuthPanel`. So the `mac-*` and `gallery-*`
  rules are kept alive by components that no longer appear on screen. Removing
  that dead code would let the old language be deleted outright, but it is a
  separate change and is not attempted here.

## Outcome (2026-09-11)

All 8 tasks landed. What is true now, plainly:

**What matches the design.** `App.js`'s `MenuBar` and marquee are gone, both
pages sit on the shared `TopBar`, `MyBrandsPanel` and `FavouritesPanel` each
have their own CSS file, and the objective checks below pass. `global.css` is
781 lines, down from 1882 at the start (804 after Tasks 1-7, minus 23 lines of
marquee rules removed in this task).

**What came out differently from this document, and why:**

1. Favourites' status bar is laid out in normal flow in the main column, not
   `position: fixed; left: 280px` like High Fashion's. It lands in the same
   visual position today, but stays aligned if the sidebar width ever changes,
   instead of needing a matching edit. This was a deliberate deviation made
   during Task 6, not an oversight.

2. Task 6's review found four defects in this document's own specified
   component code, all fixed before merge:
   - Removing a collection's last look left the user on a dead filter with no
     row highlighted.
   - The thumb strip had no auto-scroll behind its deliberately hidden
     scrollbar, so the active thumb could slide off-screen.
   - The index clamp ran one render late, briefly unmounting the single view.
   - The status bar paired a look number with a favourites count, which could
     render as nonsense like "LOOK 19 / 3".

   A second review round found the first fix itself measured from `<body>`,
   which is wrong for Favourites: unlike High Fashion's `.hf2-main`, Favourites
   has no positioned ancestor, so the 281px sidebar width leaked into the
   offset. That was corrected using the `getBoundingClientRect` delta approach
   already used by `HighFashionV2`'s year strip.

3. `MacModal.js` was in scope per the design's file list but turned out to have
   no consumers anywhere in `src/` — nothing imports it. It was dropped from
   scope. The dialogs the design describes are actually built on the
   `modern-modal-*` class family, which `MyBrandsPanel` solely owned and which
   moved into `MyBrandsPanel.css` as planned.

4. Step 2 of this task expected the `mac-panel` / `mac-button` / `gallery-item`
   consumer list to be `CollectionsPanel.js`, `SeasonsPanel.js`,
   `ImageViewerPanel.js`, `VideoModal.js` and `MenuBar.js`. The actual grep also
   returns `MacModal.js` (it uses `mac-button` internally, at lines 150 and
   160) — a sixth consumer this document did not list. `MacModal.js` having no
   *importers* (point 3 above) and `MacModal.js` *itself referencing*
   `mac-button` are two separate facts; both are true. None of the six files
   were touched.

**Visual verification: not run.** No task in this conversion, including this
one, opened the app in a browser and compared it against High Fashion. Every
task's visual gate was deferred because the dev server needs a live database
and an authenticated session, neither of which was available in this
environment. Everything above is verified by `npm run build`, targeted grep
assertions, and code review only. Step 4 of this task's checklist — the
side-by-side comparison of top bar, sidebar, section headers, selection
treatment, type scale, corner radius, and scrollbars against High Fashion —
has not been performed by anyone. It is the one check that decides whether
this conversion actually succeeded, and it is still owned by whoever runs the
app next.

**Left alone, on purpose, per this task's constraints:**
- `SeasonsPanel`, `CollectionsPanel` and `ImageViewerPanel` are imported by
  `App.js` but never rendered — confirmed again in this task by grepping
  `App.js` for `<SeasonsPanel`, `<CollectionsPanel`, `<ImageViewerPanel`
  (no matches) versus their `import` lines (present). The old language stays
  alive in `global.css` only because these three plus `VideoModal` and
  `MenuBar` still reference `mac-*` / `gallery-*` classes.
- `MenuBar.js` is not imported by `App.js` or anywhere else in `src/` (a plain
  `grep -rln "MenuBar" src --include="*.js"` turns up only
  `FavouritesPanel.js`, in a comment, and `MenuBar.js` itself). It is fully
  orphaned, not merely unrendered.
- `global.css` remains large and holds rules for components that no longer
  appear on screen.
