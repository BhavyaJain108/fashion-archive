# Favourites and My Brands Design Language Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `FavouritesPanel` and `MyBrandsPanel` from the old macOS-glass language to the brutalist-white language `HighFashionV2` already uses, so all three pages read as one app.

**Architecture:** A new `src/styles/archive.css` holds the language once — tokens plus reusable primitives lifted from `HighFashionV2.css`. Per-page stylesheets (`MyBrandsPanel.css`, `FavouritesPanel.css`) build on it, and the old rules move out of the shared `global.css` as their replacements land. `HighFashionV2.css` is deliberately not refactored, so the one already-working page cannot regress.

**Tech Stack:** React 18, Create React App (`react-scripts` 5), plain CSS with custom properties. No CSS framework, no preprocessor, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-11-favourites-mybrands-design-language-design.md`

## There is no JavaScript test suite

This matters for every task below, so read it before starting.

`tests/` holds Python only (`api`, `db`, `unit`). No `*.test.js` exists anywhere
outside `node_modules`, and `@testing-library/*` is not installed — `package.json`
lists exactly `fuse.js`, `react`, `react-dom` and `react-scripts`. Standing up
Jest and React Testing Library to assert on CSS would mean adding dependencies
and inventing a test infrastructure this project has never had, for a change that
is presentation-only. The approved spec's verification is a clean build plus a
visual check, and this plan does not add a framework.

So the usual red/green cycle is replaced, per task, by two gates:

1. **Objective checks** — `npm run build` must compile clean, plus `grep`
   assertions with exact expected counts. These are mechanical and cannot be
   fudged: "no VT323 in this file" and "no `--macos-accent` in this file" are
   verifiable facts, and every task states its own.
2. **Visual checks** — a numbered list of what to look at and what it must look
   like, written so a reviewer who has never seen the page can run it.

Report both honestly. If a visual check fails, say which one and what you saw;
do not report a task complete on a clean build alone.

## Global Constraints

- **Palette, verbatim.** `#ffffff` page ground, `#fafafa` sidebars and strips,
  `#e0e0e0` hairlines, `#ededed` rules inside a grouped block, `#000000`
  selected/active text, `#666666` body, `#999999` labels and idle controls,
  `#cccccc` empty states and counts, `#cc0000` destructive only. No other colour
  may be introduced.
- **Font stack, verbatim:** `'JetBrains Mono', 'SF Mono', 'Monaco', monospace`.
  Never VT323.
- **Type scale:** 9px badges and micro-labels, 10px section headers, 11px
  controls and secondary text, 12px body and list rows, 13px the TopBar logo.
  Nothing larger.
- **Zero border radius** anywhere on these pages. No `box-shadow`. No
  `backdrop-filter`.
- **Section headers** are 10px, `text-transform: uppercase`, `letter-spacing:
  0.15em`, colour `#999999`.
- **Selection** is black, never blue: bold black text, a 2px black left border,
  over an `rgba(0,0,0,0.03)` wash. Hover is `rgba(0,0,0,0.02)`.
- **Scrollbars** are 4–6px wide, square, `#dddddd` thumb on a transparent track.
- **Behaviour is not changed.** No API call, response shape, state shape or
  handler logic is altered except the two prop moves in Task 2. If a task tempts
  you to fix a bug, leave it and report it instead.
- **Do not touch** `HighFashionV2.js`, `HighFashionV2.css`, `TopBar.js`,
  `TopBar.css`, `MenuBar.js`, `MacModal.js`, `ScrapeConsole.js`, or
  `services/api.js`.
- **Commit after every task.** End each commit message with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `web_ui/src/styles/archive.css` | **New.** Tokens and primitives. The single source of the language. Imported once, by `index.js`. |
| `web_ui/src/components/MyBrandsPanel.css` | **New.** Everything My Brands needs: sidebar, footer, toolbar, grid, cards, badges, dialogs. |
| `web_ui/src/components/FavouritesPanel.css` | **New.** Everything Favourites needs: sidebar, grid and single views, thumb strip, status bar. |
| `web_ui/src/components/ProductDetailPanel.css` | **New.** The product detail drawer, moved out of `global.css`. |
| `web_ui/src/styles/global.css` | Shrinks. Loses the `my-brands`, `brand-*`, `nav-*`, `product-*`, `search-*`, `tile-*`, `detail-*`, `modern-*` and `marquee-*` rules. Keeps `mac-*` and `gallery-*`, which other components still reference. |
| `web_ui/src/components/FavouritesPanel.js` | Rewritten to the High Fashion layout anatomy. |
| `web_ui/src/components/MyBrandsPanel.js` | Structure kept. Gains a `TopBar`, loses inline styling, gains new class names only where a badge or label changes wording. |
| `web_ui/src/components/ProductDetailPanel.js` | Imports its new stylesheet. Markup unchanged apart from the close glyph. |
| `web_ui/src/App.js` | Drops the `MenuBar` + marquee block and the `currentView` state; passes chrome props to both panels. |

Why these boundaries: the three panel stylesheets each sit next to the single
component that consumes them, which is the pattern `HighFashionV2.css` and
`TopBar.css` already establish. `global.css` is 1882 lines and shared by
components outside this change, so rules leave it only when the component being
converted is provably their only consumer.

---

### Task 1: The shared language

Foundation. Nothing consumes it yet, so this task changes nothing on screen —
that is the expected result, and the point: it lands the palette in one place
before three stylesheets start referring to it.

**Files:**
- Create: `web_ui/src/styles/archive.css`
- Modify: `web_ui/src/index.js`

**Interfaces:**
- Consumes: nothing.
- Produces: the custom properties `--ar-bg`, `--ar-bg-sub`, `--ar-line`,
  `--ar-line-soft`, `--ar-ink`, `--ar-ink-2`, `--ar-ink-3`, `--ar-ink-4`,
  `--ar-danger`, `--ar-font`, `--ar-wash`, `--ar-wash-strong`; and the classes
  `.ar-page`, `.ar-content`, `.ar-sidebar`, `.ar-sidebar-scroll`,
  `.ar-section-header`, `.ar-list-item`, `.ar-chip`, `.ar-btn`, `.ar-btn-block`,
  `.ar-btn-danger`, `.ar-input`, `.ar-select`, `.ar-status-bar`, `.ar-scroll`,
  `.ar-empty`, `.ar-loading`. Tasks 3–8 use these by name.

- [ ] **Step 1: Create the stylesheet**

Create `web_ui/src/styles/archive.css` with exactly this content:

```css
/* ---------------------------------------------------------------------
   The archive design language.

   Every value here was lifted from HighFashionV2.css, which is where the
   language was first built. That file keeps its literal hex values; these
   tokens spell the same colours so the pages agree. Migrating High Fashion
   onto the tokens is deliberately left alone — it works, and this change
   has no reason to touch it.
   --------------------------------------------------------------------- */

:root {
  --ar-bg: #ffffff;          /* page ground */
  --ar-bg-sub: #fafafa;      /* sidebars, strips, toolbars */
  --ar-line: #e0e0e0;        /* hairline rules */
  --ar-line-soft: #ededed;   /* rules inside a grouped block */
  --ar-ink: #000000;         /* selected / active */
  --ar-ink-2: #666666;       /* body */
  --ar-ink-3: #999999;       /* labels, idle controls */
  --ar-ink-4: #cccccc;       /* empty states, counts, disabled */
  --ar-danger: #cc0000;      /* destructive confirmation ONLY */

  --ar-wash: rgba(0, 0, 0, 0.02);         /* hover */
  --ar-wash-strong: rgba(0, 0, 0, 0.03);  /* selected */

  --ar-font: 'JetBrains Mono', 'SF Mono', 'Monaco', monospace;
}

/* --- Page shell ---------------------------------------------------- */

.ar-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100%;
  background: var(--ar-bg);
  font-family: var(--ar-font);
  font-size: 12px;
  color: var(--ar-ink-2);
}

.ar-content {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* --- Sidebar ------------------------------------------------------- */

.ar-sidebar {
  width: 280px;
  min-width: 280px;
  background: var(--ar-bg-sub);
  border-right: 1px solid var(--ar-line);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.ar-sidebar-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* --- Labels -------------------------------------------------------- */

.ar-section-header {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  padding: 14px 12px 10px;
  color: var(--ar-ink-3);
  display: flex;
  justify-content: space-between;
  flex-shrink: 0;
}

.ar-section-header .count {
  color: var(--ar-ink-4);
}

/* --- List rows ----------------------------------------------------- */

.ar-list-item {
  font-size: 12px;
  padding: 6px 12px;
  cursor: pointer;
  transition: all 0.1s ease;
  border-left: 2px solid transparent;
  display: flex;
  align-items: flex-start;
}

.ar-list-item:hover {
  color: var(--ar-ink);
  background: var(--ar-wash);
}

.ar-list-item.selected {
  color: var(--ar-ink);
  font-weight: 500;
  border-left-color: var(--ar-ink);
  background: var(--ar-wash-strong);
}

/* --- Chips (mutually exclusive modes) ------------------------------ */

.ar-chip {
  appearance: none;
  border: none;
  border-radius: 0;
  background: transparent;
  font-family: inherit;
  font-size: 11px;
  line-height: 20px;
  padding: 0 6px;
  color: var(--ar-ink-3);
  cursor: pointer;
  white-space: nowrap;
  border-left: 2px solid transparent;
  text-align: left;
  transition: color 0.1s ease;
}

.ar-chip:hover {
  color: var(--ar-ink);
}

.ar-chip.selected {
  color: var(--ar-ink);
  font-weight: 700;
  border-left-color: var(--ar-ink);
}

/* --- Buttons ------------------------------------------------------- */

.ar-btn {
  font-family: var(--ar-font);
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 8px 16px;
  border: 1px solid var(--ar-line);
  border-radius: 0;
  background: var(--ar-bg);
  color: var(--ar-ink-3);
  cursor: pointer;
  transition: all 0.15s ease;
}

.ar-btn:hover {
  border-color: var(--ar-ink);
  color: var(--ar-ink);
}

.ar-btn.active {
  background: var(--ar-ink);
  border-color: var(--ar-ink);
  color: var(--ar-bg);
}

.ar-btn:disabled {
  color: var(--ar-ink-4);
  border-color: var(--ar-line);
  cursor: default;
}

.ar-btn-block {
  display: block;
  width: 100%;
  text-align: center;
}

/* The one place colour is allowed: discarding something irreversibly. */
.ar-btn-danger {
  color: var(--ar-danger);
  border-color: var(--ar-danger);
}

.ar-btn-danger:hover {
  background: var(--ar-danger);
  border-color: var(--ar-danger);
  color: var(--ar-bg);
}

/* --- Fields -------------------------------------------------------- */

.ar-input,
.ar-select {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px;
  border: 1px solid var(--ar-line);
  border-radius: 0;
  font-family: var(--ar-font);
  font-size: 11px;
  background: var(--ar-bg);
  color: var(--ar-ink);
  outline: none;
  transition: border-color 0.15s ease;
}

.ar-input:focus,
.ar-select:focus {
  border-color: var(--ar-ink);
}

.ar-input::placeholder {
  color: var(--ar-ink-4);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.ar-select {
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

/* --- Status bar ---------------------------------------------------- */

.ar-status-bar {
  height: 36px;
  flex-shrink: 0;
  background: var(--ar-bg);
  border-top: 1px solid var(--ar-line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  font-size: 11px;
  color: var(--ar-ink-3);
}

.ar-status-bar .active {
  color: var(--ar-ink);
  font-weight: 600;
}

/* --- Scrollbars ---------------------------------------------------- */

.ar-scroll::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.ar-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.ar-scroll::-webkit-scrollbar-thumb {
  background: #dddddd;
  border-radius: 0;
}

.ar-scroll::-webkit-scrollbar-thumb:hover {
  background: var(--ar-ink-4);
}

/* --- Empty and loading -------------------------------------------- */

.ar-empty,
.ar-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px 12px;
  text-align: center;
  font-size: 11px;
  color: var(--ar-ink-4);
}

.ar-empty .headline,
.ar-loading .headline {
  text-transform: uppercase;
  letter-spacing: 0.15em;
}
```

- [ ] **Step 2: Import it once, ahead of `global.css`**

Read `web_ui/src/index.js` first. It is 23 lines and currently imports
`./styles/global.css`. Add the `archive.css` import on the line **before** it, so
that `global.css` still wins any accidental collision and this task cannot change
how anything currently looks:

```javascript
import './styles/archive.css';
import './styles/global.css';
```

- [ ] **Step 3: Objective checks**

```bash
cd web_ui && npm run build
```

Expected: `Compiled successfully.` If instead you get `Compiled with warnings`,
compare against a build from before this task — a pre-existing warning is fine
to leave, a new one is not.

```bash
cd web_ui && grep -c "ar-" src/styles/archive.css && grep -n "VT323\|macos-\|border-radius: [1-9]\|box-shadow\|backdrop-filter" src/styles/archive.css
```

Expected: the count prints a number above 50, and the second `grep` prints
**nothing** and exits 1. Any hit is a constraint violation — the new file must not
reference the old palette or reintroduce radius, shadow or blur.

- [ ] **Step 4: Visual check**

Run the app (`npm start` in `web_ui`, with the backend up per `web_ui/README.md`
— same hostname for both, or the session cookie is dropped and every request
401s). Open all three pages.

Expected: **nothing looks different yet.** `archive.css` defines `.ar-*` classes
that no markup uses. If any page changed, an `.ar-*` selector is colliding with
an existing class name — find it and rename the `.ar-*` one.

- [ ] **Step 5: Commit**

```bash
git add web_ui/src/styles/archive.css web_ui/src/index.js
git commit -m "Add the archive design language as shared tokens

Lifts the palette, type scale and primitives out of HighFashionV2.css
into one file, so Favourites and My Brands can refer to the same values
rather than each spelling them again.

HighFashionV2.css keeps its literal hex values. The tokens match it, and
migrating that file is left alone — it works, and this change has no
reason to touch it.

Nothing consumes these classes yet, so nothing looks different.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Uniform chrome

Both pages start rendering the same `TopBar` as High Fashion, and `App.js` stops
drawing the old `MenuBar` and marquee. After this task the top of all three pages
matches. The bodies are still old-language — that is expected, and Tasks 3–8 fix
them.

This is also where the two prop moves happen, and they must happen together with
the chrome: `MenuBar` is the only writer of `currentView`, so removing it while
`FavouritesPanel` still reads that prop would break the page.

**Files:**
- Modify: `web_ui/src/App.js` (the `MenuBar` + marquee block at lines 358-385, `currentView` at 32, `handleViewChange` at 340-342, the panel renders at 390-402)
- Modify: `web_ui/src/components/FavouritesPanel.js`
- Modify: `web_ui/src/components/MyBrandsPanel.js`

**Interfaces:**
- Consumes: `TopBar` from `./TopBar`, whose signature is already
  `TopBar({ currentPage, onPageSwitch, currentUser, onLogout })`.
- Produces: `FavouritesPanel({ currentPage, onPageSwitch, currentUser, onLogout })`
  and `MyBrandsPanel({ currentPage, onPageSwitch, currentUser, onLogout })`. Neither
  takes `currentView` any more. `FavouritesPanel` holds `groupMode` locally, a
  string that is `'view-all'` or `'by-collection'`. Tasks 6 and 7 rely on that
  name.

- [ ] **Step 1: Give `FavouritesPanel` the chrome and local mode**

In `web_ui/src/components/FavouritesPanel.js`, change the import block and the
signature. The component currently begins:

```javascript
import React, { useState, useEffect } from 'react';
import { FashionArchiveAPI } from '../services/api';

function FavouritesPanel({ currentView }) {
```

Replace with:

```javascript
import React, { useState, useEffect } from 'react';
import TopBar from './TopBar';
import { FashionArchiveAPI } from '../services/api';

function FavouritesPanel({ currentPage, onPageSwitch, currentUser, onLogout }) {
  // Was lifted into App so the old MenuBar's View menu could write it. That
  // menu is gone, and this page is the only reader, so it lives here now.
  const [groupMode, setGroupMode] = useState('view-all');
```

Then replace every remaining read of `currentView` with `groupMode`. There are
three, at lines 14, 41 and 229 of the current file:

- `switch (currentView) {` becomes `switch (groupMode) {`
- `if (currentView !== 'by-collection') return [];` becomes
  `if (groupMode !== 'by-collection') return [];`
- `{currentView === 'by-collection' ? (` becomes
  `{groupMode === 'by-collection' ? (`

`setGroupMode` has no caller until Task 6 builds the chip row. Leave it unused
for now — CRA's ESLint does not warn on an unused destructured `useState` setter.

- [ ] **Step 2: Render `TopBar` in `FavouritesPanel`**

The component has three `return` statements — loading, empty, and the main view.
All three currently open with `<div className="columns-container">`. Add the
`TopBar` as the first child of each, so the chrome is present in every state
rather than appearing only once favourites have loaded:

```javascript
      <div className="columns-container">
        <TopBar
          currentPage={currentPage}
          onPageSwitch={onPageSwitch}
          currentUser={currentUser}
          onLogout={onLogout}
        />
```

Leave the rest of each return alone, including the `paddingTop: '75px'` inline
styles. They are wrong now, and Tasks 6 and 7 delete them along with the rest of
the layout.

- [ ] **Step 3: Give `MyBrandsPanel` the chrome**

In `web_ui/src/components/MyBrandsPanel.js`, add the import after the `Fuse` line:

```javascript
import TopBar from './TopBar';
```

Change the signature at line 7 from `function MyBrandsPanel() {` to:

```javascript
function MyBrandsPanel({ currentPage, onPageSwitch, currentUser, onLogout }) {
```

It never read `currentView`, so nothing else changes in its logic.

This component also has two `return`s — the loading branch and the main view.
Wrap both so the page becomes a column holding the chrome and then the content.
The loading branch becomes:

```javascript
  if (loading) {
    return (
      <div className="ar-page">
        <TopBar
          currentPage={currentPage}
          onPageSwitch={onPageSwitch}
          currentUser={currentUser}
          onLogout={onLogout}
        />
        <div className="ar-content">
          <div className="loading-state">Loading brands...</div>
        </div>
      </div>
    );
  }
```

And the main view's opening `<div className="ar-content">` becomes:

```javascript
    <div className="ar-page">
      <TopBar
        currentPage={currentPage}
        onPageSwitch={onPageSwitch}
        currentUser={currentUser}
        onLogout={onLogout}
      />
      <div className="ar-content">
```

Close the extra `<div>` at the end of that return — it currently ends with
`</div>\n  );\n}`, and needs one more `</div>` before the `);`.

- [ ] **Step 4: Delete the old container rule**

`.my-brands-container` reserved room for the old fixed chrome with
`height: calc(100vh - 75px)` and `margin-top: 75px`. The `TopBar` is a real
element in the flow now, so that reservation is wrong — and `.ar-page` and
`.ar-content` from Task 1 already describe the geometry the page needs.

So there is no replacement rule to write. Delete the whole
`.my-brands-container` rule from `web_ui/src/styles/global.css` (at line 805,
before your edits) and let the shared classes carry it.

- [ ] **Step 5: Strip the old chrome from `App.js`**

Delete the whole `{currentPage !== 'high-fashion' && ( ... )}` block — the
fragment holding `<MenuBar ... />` and the `mac-title-bar` marquee `<div>`, lines
358-385 inclusive. With all three pages carrying their own `TopBar`, it renders
for no page.

Then delete the now-unused `import MenuBar from './components/MenuBar';` at line
6. An unused import trips `no-unused-vars` under the CRA ESLint config, and the
build must stay warning-clean.

Do **not** delete `web_ui/src/components/MenuBar.js`. The file stays in the tree,
unrendered. It is the only home of the Research toggle, Video Test and About
dialogs, nothing else references them, and the high-fashion page already could
not reach them. Leaving the file costs nothing and keeps the option of re-homing
those three into `TopBar` later.

- [ ] **Step 6: Remove the lifted view state from `App.js`**

Delete line 32:

```javascript
  const [currentView, setCurrentView] = useState('standard'); // high-fashion: 'standard', favourites: 'view-all'
```

and the handler at lines 340-342:

```javascript
  const handleViewChange = (viewMode) => {
    setCurrentView(viewMode);
  };
```

`MenuBar` was its only writer and `FavouritesPanel` now owns the state.
`MyBrandsPanel` never read it.

- [ ] **Step 7: Pass the chrome props to both panels**

Replace the three panel renders at lines 396-402 with:

```javascript
      ) : currentPage === 'favourites' ? (
        <FavouritesPanel
          currentPage={currentPage}
          onPageSwitch={handlePageSwitch}
          currentUser={currentUser}
          onLogout={handleLogout}
        />
      ) : currentPage === 'my-brands' ? (
        <MyBrandsPanel
          currentPage={currentPage}
          onPageSwitch={handlePageSwitch}
          currentUser={currentUser}
          onLogout={handleLogout}
        />
      ) : (
        <FavouritesPanel
          currentPage={currentPage}
          onPageSwitch={handlePageSwitch}
          currentUser={currentUser}
          onLogout={handleLogout}
        />
      )}
```

- [ ] **Step 8: Objective checks**

```bash
cd web_ui && npm run build
```

Expected: `Compiled successfully.`, no new warnings. An unused-variable warning
here means a step above was missed — most likely the `MenuBar` import or
`setCurrentView`.

```bash
cd web_ui && grep -rn "currentView\|handleViewChange\|onViewChange" src/ --include=*.js | grep -v MenuBar.js
```

Expected: **no output.** `MenuBar.js` still mentions them internally, which is
why it is excluded — it is unrendered, and untouched by design.

```bash
cd web_ui && grep -c "MenuBar\|marquee" src/App.js
```

Expected: `0`.

```bash
cd web_ui && grep -rln "TopBar" src/components/FavouritesPanel.js src/components/MyBrandsPanel.js
```

Expected: both filenames print.

- [ ] **Step 9: Visual check**

Run the app and check, in order:

1. All three pages show the same 48px white top bar: `ARCHIVE` at the left,
   `Collections / Favourites / My Brands` centred, username and `LOGOUT` right.
2. The scrolling "Fashion Archive Browser" marquee is gone from every page, as
   are the `Tools / Pages / View` menus.
3. The top bar's current-page link is the black, bold one, on each of the three
   pages in turn.
4. Clicking each of the three links navigates, and `LOGOUT` still signs out.
5. Favourites and My Brands still function: favourites load and the
   previous/next buttons move between them; brands expand, categories select,
   products load. The bodies still look old — pixel font, blue selection. That is
   correct at this point.
6. No page has a gap or overlap where the old fixed chrome used to be. My Brands
   in particular should have its sidebar starting directly under the top bar.

- [ ] **Step 10: Commit**

```bash
git add web_ui/src/App.js web_ui/src/components/FavouritesPanel.js web_ui/src/components/MyBrandsPanel.js web_ui/src/styles/global.css
git commit -m "Put all three pages on the shared TopBar

Favourites and My Brands were crowned by the old MenuBar and a scrolling
marquee, drawn by App.js for every page except high-fashion. Both now
render the same TopBar that High Fashion does, and that block is gone.

The view state moves with the chrome. MenuBar was the only writer of
App's currentView, and Favourites the only reader, so it becomes local
groupMode state there. MyBrandsPanel never read the prop.

MenuBar.js stays in the tree, unrendered. It is the only home of the
Research toggle, Video Test and About dialogs; nothing else references
them and the high-fashion page already could not reach them.

Bodies are still in the old language. Following commits convert them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---
### Task 3: My Brands sidebar and footer

The first task that changes how something looks. My Brands keeps its structure
throughout — it is already a 280px sidebar beside a scrolling gallery — so this
and the next two tasks are almost entirely CSS.

A note on deleting from `global.css`: line numbers shift as you edit, so work by
selector name, not by line. The ranges quoted are where the rules stand before
this task begins.

**Files:**
- Create: `web_ui/src/components/MyBrandsPanel.css`
- Modify: `web_ui/src/components/MyBrandsPanel.js`
- Modify: `web_ui/src/styles/global.css` (remove the sidebar rules, roughly lines 810-1040)

**Interfaces:**
- Consumes: the tokens and `.ar-btn`, `.ar-btn-block`, `.ar-btn-danger`,
  `.ar-scroll` from Task 1; the `.ar-page` / `.ar-content` shell Task 2 put on
  the page.
- Produces: `MyBrandsPanel.css` as the page's stylesheet, imported by
  `MyBrandsPanel.js`. Tasks 4 and 5 append to this same file.

- [ ] **Step 1: Create the stylesheet with the sidebar rules**

Create `web_ui/src/components/MyBrandsPanel.css`:

```css
/* My Brands — the archive language. Tokens live in styles/archive.css.
   The page shell is .ar-page + .ar-content from that file; this sheet only
   describes what is particular to this page. */

/* --- Sidebar ------------------------------------------------------- */

.brand-sidebar {
  width: 280px;
  min-width: 280px;
  background: var(--ar-bg-sub);
  border-right: 1px solid var(--ar-line);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.brand-sidebar-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 0;
}

.brand-section {
  margin-bottom: 0;
}

/* A brand: 12px uppercase, letterspaced. Black and bold once expanded, so
   the open brand is findable in a long list without an icon. */
.brand-name {
  display: flex;
  align-items: baseline;
  padding: 7px 12px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ar-ink-3);
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: all 0.1s ease;
  user-select: none;
}

.brand-name:hover {
  color: var(--ar-ink);
  background: var(--ar-wash);
}

.brand-name.expanded {
  color: var(--ar-ink);
  font-weight: 700;
  border-left-color: var(--ar-ink);
  background: var(--ar-wash-strong);
}

.brand-name.brand-loading {
  color: var(--ar-ink-4);
}

.brand-name.brand-long-pressing {
  cursor: progress;
}

.brand-name-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* "loading..." became "scraping" — it is a scrape, and the word is honest. */
.brand-loading-text {
  font-size: 9px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--ar-ink-4);
  flex-shrink: 0;
  padding-left: 8px;
}

.brand-categories {
  padding-bottom: 4px;
}

/* --- Category tree ------------------------------------------------- */

.nav-item {
  display: flex;
  align-items: baseline;
  padding: 5px 12px;
  font-size: 11px;
  color: var(--ar-ink-3);
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: all 0.1s ease;
  user-select: none;
}

.nav-item:hover {
  color: var(--ar-ink);
  background: var(--ar-wash);
}

.nav-selected {
  color: var(--ar-ink);
  border-left-color: var(--ar-ink);
  background: var(--ar-wash-strong);
}

.nav-parent {
  font-weight: 500;
}

.nav-icon {
  margin-right: 8px;
  font-size: 9px;
  width: 8px;
  flex-shrink: 0;
  color: var(--ar-ink-4);
  display: inline-block;
}

.nav-item:hover .nav-icon,
.nav-selected .nav-icon {
  color: var(--ar-ink-2);
}

.nav-bullet {
  display: none;
}

.nav-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-text-bold {
  flex: 1;
  min-width: 0;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-count {
  margin-left: auto;
  padding-left: 8px;
  font-size: 10px;
  color: var(--ar-ink-4);
  flex-shrink: 0;
}

/* --- Footer -------------------------------------------------------- */

.add-brand-footer {
  padding: 12px;
  border-top: 1px solid var(--ar-line);
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}

/* Removing a brand discards everything scraped for it, so the button
   reddens once arm-mode is on — the one place colour is allowed. */
.brand-name.selected-for-removal {
  color: var(--ar-danger);
  border-left-color: var(--ar-danger);
  background: var(--ar-wash-strong);
  text-decoration: line-through;
  text-decoration-color: var(--ar-danger);
}

.brand-name.selected-for-removal:hover {
  color: var(--ar-danger);
}

.remove-brand-list {
  margin-top: 12px;
  padding-left: 16px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ar-ink);
  list-style: none;
}

.remove-brand-list li {
  margin-bottom: 4px;
}

.remove-brand-list li::before {
  content: '— ';
  color: var(--ar-ink-4);
}
```

- [ ] **Step 2: Import the stylesheet**

In `web_ui/src/components/MyBrandsPanel.js`, add after the `ScrapeConsole`
import:

```javascript
import './MyBrandsPanel.css';
```

- [ ] **Step 3: Mark the expanded brand, and rename the scrape label**

Two small markup changes. In the brand row's `className`, add the `expanded`
state the new CSS styles. The line currently reads:

```javascript
                  className={`brand-name ${isScraping ? 'brand-loading' : ''} ${removeMode && selectedForRemoval.has(brand.brand_id) ? 'selected-for-removal' : ''}`}
```

Replace with:

```javascript
                  className={`brand-name ${isExpanded && !removeMode ? 'expanded' : ''} ${isScraping ? 'brand-loading' : ''} ${removeMode && selectedForRemoval.has(brand.brand_id) ? 'selected-for-removal' : ''}`}
```

`isExpanded` is already in scope, assigned just above from
`expandedBrands[brand.brand_id]`.

Then change the scrape label on the next line from:

```javascript
                  {isScraping && !removeMode && <span className="brand-loading-text"> loading...</span>}
```

to:

```javascript
                  {isScraping && !removeMode && <span className="brand-loading-text">scraping</span>}
```

The CSS uppercases it; the leading space is no longer needed because
`.brand-loading-text` carries `padding-left`.

- [ ] **Step 4: Convert the footer buttons**

Replace the three footer buttons' classes. `remove-brand-button` (the armed one)
becomes:

```javascript
            <button
              className="ar-btn ar-btn-block ar-btn-danger"
              onClick={() => {
                if (selectedForRemoval.size > 0) {
                  setShowRemoveConfirm(true);
                } else {
                  setRemoveMode(false);
                  setSelectedForRemoval(new Set());
                }
              }}
            >
              {selectedForRemoval.size > 0
                ? `Remove ${selectedForRemoval.size} Brand${selectedForRemoval.size > 1 ? 's' : ''}`
                : 'Cancel'}
            </button>
```

and the two idle buttons become:

```javascript
              <button
                className="ar-btn ar-btn-block"
                onClick={() => setShowAddBrandModal(true)}
              >
                + Add Brand
              </button>
              <button
                className="ar-btn ar-btn-block"
                onClick={() => setRemoveMode(true)}
              >
                Remove
              </button>
```

The labels shorten because `.ar-btn` uppercases and letterspaces them, and
"+ ADD NEW BRAND" at `0.1em` overflows 280px minus padding. The handlers are
untouched.

- [ ] **Step 5: Make the sidebar scrollbar a hairline**

Add `ar-scroll` to the sidebar's scrolling element:

```javascript
        <div className="brand-sidebar-content ar-scroll">
```

- [ ] **Step 6: Delete the superseded rules from `global.css`**

Remove these rules, which `MyBrandsPanel.css` now owns. `MyBrandsPanel` is their
only consumer, verified in Step 7:

`.brand-sidebar`, `.brand-sidebar-content`, `.brand-section`, `.brand-name` and all its variants,
`.brand-expand-icon`, `.brand-name-text`, `.brand-loading-text`,
`.brand-categories`, `.nav-item`, `.nav-leaf`, `.nav-parent`, `.nav-selected`,
`.nav-icon`, `.nav-bullet`, `.nav-text`, `.nav-text-bold`, `.nav-count`,
`.add-brand-footer`, `.add-brand-button`, `.remove-brand-button`,
`.remove-brand-button-idle`, `.remove-brand-list`.

Also delete the `.brand-sidebar-content` half of the shared scrollbar rules — the
selector list `.brand-sidebar-content::-webkit-scrollbar, .product-gallery::-webkit-scrollbar`
and its siblings. Leave the `.product-gallery` half in place; Task 4 removes it.

Keep `.modern-button-danger` for now — the dialogs still use it until Task 5.

- [ ] **Step 7: Objective checks**

```bash
cd web_ui && npm run build
```

Expected: `Compiled successfully.`

```bash
cd web_ui && grep -n "VT323\|macos-accent\|macos-selected-bg\|backdrop-filter\|border-radius: [1-9]" src/components/MyBrandsPanel.css
```

Expected: no output, exit 1.

```bash
cd web_ui && grep -c "brand-sidebar\|\.brand-name\|\.nav-item\|add-brand-footer" src/styles/global.css
```

Expected: `0` — the rules are gone from the shared sheet, not duplicated across
both.

```bash
cd web_ui && grep -rn "add-brand-button\|remove-brand-button" src/
```

Expected: no output. Both class names are retired; if either still appears in
`MyBrandsPanel.js` a footer button was missed in Step 4.

- [ ] **Step 8: Visual check**

Open My Brands. Against High Fashion's sidebar, confirm:

1. Brand names are small uppercase monospace, letterspaced — not large pixel
   type. Idle brands are grey.
2. Clicking a brand expands it and the row goes black, bold, with a 2px black bar
   on its left edge and a barely-there grey wash. No blue anywhere.
3. Category rows are 11px grey, and the selected one takes the same black left
   bar. Carets are small light-grey `▾`/`▸`. Product counts are pale grey at the
   right edge.
4. A brand mid-scrape shows a pale `SCRAPING` at its right, and is not clickable.
5. The footer holds two full-width hairline boxes, `+ ADD BRAND` over `REMOVE`,
   both grey. Hovering either turns its border and text black. Neither is blue.
6. Click `REMOVE`: the footer becomes a single red-bordered button. Select a
   brand — it goes red and struck through. Hovering the button fills it red.
   Press it with nothing selected and it reads `CANCEL` and exits arm-mode.
7. The sidebar scrollbar is a thin pale line, not an 8px rounded bar.
8. Long brand and category names truncate with an ellipsis rather than wrapping
   or pushing the count off the edge.

Do not confirm the removal in check 6 unless you have a brand you are willing to
lose — it discards that brand's scraped products. Cancel out instead.

- [ ] **Step 9: Commit**

```bash
git add web_ui/src/components/MyBrandsPanel.css web_ui/src/components/MyBrandsPanel.js web_ui/src/styles/global.css
git commit -m "Convert the My Brands sidebar to the archive language

Brand rows go from 27px VT323 with a blue hover tint to 12px uppercase
monospace, taking the black left-border selection High Fashion uses. The
glass blur becomes a flat #fafafa panel behind a hairline.

The footer's blue Add and red Remove pills become hairline boxes. Red
survives only once removal is armed, since confirming it discards
everything scraped for that brand.

'loading...' becomes 'scraping', which is what is happening.

The rules move to MyBrandsPanel.css rather than staying in the shared
global.css, where this panel was their only consumer.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: My Brands gallery, cards and badges

**Files:**
- Modify: `web_ui/src/components/MyBrandsPanel.css` (append)
- Modify: `web_ui/src/components/MyBrandsPanel.js`
- Modify: `web_ui/src/styles/global.css` (remove the gallery, toolbar and tile rules)

**Interfaces:**
- Consumes: the tokens, `.ar-input`, `.ar-select`, `.ar-toolbar`, `.ar-scroll`,
  `.ar-loading` from Task 1; `MyBrandsPanel.css` from Task 3.
- Produces: nothing new that later tasks depend on.

- [ ] **Step 1: Append the gallery rules**

Add to the end of `web_ui/src/components/MyBrandsPanel.css`:

```css
/* --- Gallery ------------------------------------------------------- */

.product-gallery {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  background: var(--ar-bg);
}

/* --- Search and sort ----------------------------------------------- */

.product-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 12px 24px;
  background: var(--ar-bg);
  border-bottom: 1px solid var(--ar-line);
  position: sticky;
  top: 0;
  z-index: 2;
  flex-shrink: 0;
}

.search-wrapper {
  flex: 1;
  position: relative;
  min-width: 0;
}

.product-sort-select {
  width: auto;
  min-width: 150px;
  flex-shrink: 0;
}

.search-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  max-height: 220px;
  overflow-y: auto;
  background: var(--ar-bg);
  border: 1px solid var(--ar-line);
  border-top: none;
  border-radius: 0;
  z-index: 10;
}

.search-dropdown-item {
  padding: 7px 12px;
  font-family: var(--ar-font);
  font-size: 11px;
  color: var(--ar-ink-3);
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-left: 2px solid transparent;
  transition: all 0.1s ease;
}

.search-dropdown-item:hover,
.search-dropdown-item.highlighted {
  color: var(--ar-ink);
  background: var(--ar-wash-strong);
  border-left-color: var(--ar-ink);
}

.dropdown-cat-name strong {
  font-weight: 700;
  color: var(--ar-ink);
}

/* --- Grid ---------------------------------------------------------- */

/* auto-fill rather than the old fixed four columns: four columns crushed
   the tiles once the detail drawer opened on a narrow window. */
.product-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
  align-content: start;
  padding: 24px;
  width: 100%;
}

.product-card {
  display: flex;
  flex-direction: column;
  background: var(--ar-bg);
  border-radius: 0;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.15s ease;
}

.product-card:hover {
  transform: translateY(-2px);
}

.product-card.selected .product-image {
  outline: 2px solid var(--ar-ink);
  outline-offset: -2px;
}

.product-image {
  position: relative;
  width: 100%;
  aspect-ratio: 3 / 4;
  overflow: hidden;
  background: #f5f5f5;
  display: flex;
  align-items: center;
  justify-content: center;
}

.product-image img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  transition: opacity 0.15s ease;
}

.product-card:hover .product-image img {
  opacity: 0.9;
}

/* Left-aligned, small: the tile is a catalogue entry, not a headline. */
.product-info {
  padding: 8px 0;
  text-align: left;
}

.product-brand {
  font-size: 9px;
  font-weight: 400;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--ar-ink-3);
  margin-bottom: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-name {
  font-size: 11px;
  font-weight: 400;
  color: var(--ar-ink);
  margin-bottom: 4px;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.product-price {
  font-size: 11px;
  font-weight: 600;
  color: var(--ar-ink);
}

.product-price-strike {
  text-decoration: line-through;
  color: var(--ar-ink-4);
  font-size: 10px;
  margin-right: 6px;
  font-weight: 400;
}

/* --- Badges -------------------------------------------------------- */

.tile-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  font-size: 9px;
  font-weight: 400;
  padding: 3px 6px;
  background: var(--ar-bg);
  border: 1px solid var(--ar-ink-2);
  color: var(--ar-ink-2);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  border-radius: 0;
  z-index: 2;
}

.tile-badge-bad {
  background: var(--ar-bg);
  border-color: var(--ar-ink-2);
  color: var(--ar-ink-2);
}

/* Sale is the one thing worth interrupting the greyscale for, so it is the
   only filled badge — black, not red. */
.tile-badge-sale {
  background: var(--ar-ink);
  border-color: var(--ar-ink);
  color: var(--ar-bg);
  font-weight: 700;
}

.tile-badge-flag {
  background: var(--ar-bg);
  border-color: var(--ar-danger);
  color: var(--ar-danger);
  left: auto;
  right: 8px;
}

/* --- Sizes --------------------------------------------------------- */

.tile-sizes {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  margin-top: 6px;
}

.tile-size {
  font-size: 9px;
  padding: 2px 5px;
  border: 1px solid var(--ar-line);
  color: var(--ar-ink-2);
  letter-spacing: 0.05em;
  border-radius: 0;
}

.tile-size.gone {
  color: var(--ar-ink-4);
  border-color: var(--ar-line);
  text-decoration: line-through;
  background: transparent;
}

/* Low stock was orange. It is weight now, not colour. */
.tile-size.low {
  border-color: var(--ar-ink-2);
  color: var(--ar-ink);
  font-weight: 700;
}

/* --- Missing image ------------------------------------------------- */

.product-card-no-image {
  opacity: 1;
}

.product-card-no-image .product-image {
  background: repeating-linear-gradient(
    45deg,
    #fafafa,
    #fafafa 6px,
    #f2f2f2 6px,
    #f2f2f2 12px
  );
}

.no-image-placeholder {
  width: 100%;
  height: 100%;
  min-height: 120px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--ar-ink-4);
  pointer-events: none;
}

.no-image-icon {
  font-size: 20px;
  font-weight: 300;
  margin-bottom: 6px;
}

.no-image-text {
  font-size: 9px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
}

/* --- States -------------------------------------------------------- */

.gallery-loading,
.loading-state,
.gallery-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  width: 100%;
  padding: 48px 24px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--ar-ink-4);
}
```

- [ ] **Step 2: Point the fields at the shared primitives**

In `web_ui/src/components/MyBrandsPanel.js`, the search input's class becomes:

```javascript
                className="ar-input"
```

and the sort select's becomes:

```javascript
              className="ar-select product-sort-select"
```

`.ar-select` carries the look; `.product-sort-select` only constrains its width
so it does not stretch.

- [ ] **Step 3: Add the hairline scrollbar to the gallery**

```javascript
      <div className="product-gallery ar-scroll">
```

- [ ] **Step 4: Shorten the placeholder text**

The search placeholder is uppercased and letterspaced by `.ar-input::placeholder`,
so `Search products...` becomes too wide. Change it to:

```javascript
                placeholder="Search"
```

- [ ] **Step 5: Delete the superseded rules from `global.css`**

Remove: `.product-gallery`, `.product-grid`, `.product-card` and its variants,
`.product-image`, `.product-info`, `.product-brand`, `.product-name`,
`.product-price`, `.product-price-strike`, `.product-toolbar`, `.search-wrapper`,
`.product-search-input`, `.product-sort-select`, `.search-dropdown`,
`.search-dropdown-item`, `.dropdown-cat-name`, `.gallery-empty`,
`.gallery-loading`, `.loading-state`, `.empty-icon`, `.empty-text`,
`.tile-badge` and its variants, `.tile-sizes`, `.tile-size` and its variants,
`.product-card-no-image`, `.no-image-placeholder`, `.no-image-icon`,
`.no-image-text`, and the remaining `.product-gallery::-webkit-scrollbar` rules.

Leave the `.detail-*` and `.modern-*` rules — Tasks 5 and 8 own those.

Leave `.gallery-item`, `.gallery-image-container` and `.gallery-look-label`
alone. Those are a different family, used by `ImageViewerPanel`, and unrelated to
`.gallery-loading` despite the shared prefix.

- [ ] **Step 6: Objective checks**

```bash
cd web_ui && npm run build
```

Expected: `Compiled successfully.`

```bash
cd web_ui && grep -n "b00020\|b85c00\|VT323\|macos-\|clamp(" src/components/MyBrandsPanel.css
```

Expected: no output. The red sale badge and orange low-stock border are both
gone, and no rule still reaches for the old palette or the fluid type scale.

```bash
cd web_ui && grep -c "product-search-input\|repeat(4, 1fr)" src/styles/global.css src/components/MyBrandsPanel.css src/components/MyBrandsPanel.js
```

Expected: `0` for all three files.

```bash
cd web_ui && grep -n "gallery-item" src/styles/global.css | head -3
```

Expected: hits. These must survive — deleting them would break
`ImageViewerPanel`.

- [ ] **Step 7: Visual check**

Open My Brands and select a category with products:

1. The toolbar is a hairline-bottomed white strip: a square search field and a
   square sort select, both small monospace. Focus the search field — its border
   goes black, not blue.
2. Type a partial category name. The dropdown is square with a hairline and no
   shadow; arrowing through it marks rows with a black left bar and pale wash,
   with the matched substring bold black.
3. Tiles are left-aligned: small grey uppercase brand, then product name at 11px
   black, then price. Nothing is centred, and no text is above 11px.
4. Narrow the window. Columns reflow and re-count rather than staying at four and
   crushing.
5. A discounted product shows a solid black `SALE` badge with the old price
   struck through in pale grey beside the new one.
6. A sold-out product shows an outlined `SOLD OUT`; an in-stock one an outlined
   `IN STOCK`. Neither is filled.
7. A product with no image shows the diagonal hatch, a `⊘`, `NO IMAGE`, and an
   outlined red `MISSING IMAGE` at the top right. This is the only red on screen.
8. Size chips are small outlined boxes; unavailable sizes are struck through in
   pale grey; low-stock sizes are bold black-bordered, not orange.
9. Click a tile — it takes a black outline, and the detail drawer opens. The
   drawer is still old-language; Task 8 converts it.
10. The gallery scrollbar is a thin pale line.

- [ ] **Step 8: Commit**

```bash
git add web_ui/src/components/MyBrandsPanel.css web_ui/src/components/MyBrandsPanel.js web_ui/src/styles/global.css
git commit -m "Convert the My Brands gallery and tiles

Tile text drops from centred clamp(16-24px) to left-aligned 9-11px, so a
tile reads as a catalogue entry rather than a headline. The grid moves
from a fixed four columns to auto-fill minmax(180px), which stops the
tiles being crushed when the detail drawer opens on a narrow window.

Badges go monochrome: Sale is the only filled one, and black rather than
#b00020. Low stock was an orange border and is now weight. The one red
left is the missing-image flag, which marks broken scrape output.

Search and sort adopt the shared field primitives, so focus is a black
border instead of a blue glow.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: My Brands dialogs

The add-brand and remove-confirm dialogs use the `modern-modal-*` family.
`MyBrandsPanel` is its only consumer — `MacModal.js` is a different component
with no consumers at all, and is not touched — so these rules move wholesale out
of `global.css`.

**Files:**
- Modify: `web_ui/src/components/MyBrandsPanel.css` (append)
- Modify: `web_ui/src/components/MyBrandsPanel.js`
- Modify: `web_ui/src/styles/global.css` (remove `.modern-*`, roughly lines 690-800 and 1030-1040)

**Interfaces:**
- Consumes: the tokens and `.ar-btn`, `.ar-btn-danger`, `.ar-input` from Task 1.
- Produces: nothing new.

- [ ] **Step 1: Append the dialog rules**

Add to the end of `web_ui/src/components/MyBrandsPanel.css`:

```css
/* --- Dialogs ------------------------------------------------------- */

/* The scrim dims; it does not blur. */
.modern-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.modern-modal {
  background: var(--ar-bg);
  border: 1px solid var(--ar-line);
  border-radius: 0;
  box-shadow: none;
  padding: 24px;
  max-width: 420px;
  width: 90%;
  font-family: var(--ar-font);
}

.modern-modal-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--ar-ink);
  padding-bottom: 12px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--ar-line);
}

.modern-modal-content {
  font-size: 11px;
  line-height: 1.5;
  color: var(--ar-ink-2);
  margin-bottom: 16px;
}

.modern-modal-actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
  margin-top: 20px;
}

.modern-error {
  background: transparent;
  border: 1px solid var(--ar-danger);
  border-radius: 0;
  padding: 10px 12px;
  color: var(--ar-danger);
  font-size: 10px;
  letter-spacing: 0.05em;
  margin-bottom: 16px;
}
```

- [ ] **Step 2: Convert the dialog controls**

In `web_ui/src/components/MyBrandsPanel.js`, four class swaps.

The add-brand URL field — `className="modern-input"` becomes:

```javascript
              className="ar-input"
```

In the add-brand actions, the Cancel button's
`className="modern-button modern-button-secondary"` becomes:

```javascript
                className="ar-btn"
```

and the submit button's `className="modern-button modern-button-primary"`
becomes:

```javascript
                className="ar-btn active"
```

`.ar-btn.active` is the black fill, which is what a primary action is in this
language.

In the remove-confirm actions, Cancel's
`className="modern-button modern-button-secondary"` becomes:

```javascript
                className="ar-btn"
```

and the confirm button's `className="modern-button modern-button-danger"`
becomes:

```javascript
                className="ar-btn ar-btn-danger"
```

- [ ] **Step 3: Keep disabled buttons legible**

`.modern-button:disabled` set `opacity: 0.5`, and `.ar-btn:disabled` instead
greys the text and keeps the border. The add-brand submit is disabled while
validating and while the field is empty, so check it still reads as disabled. No
code change unless the visual check in Step 6 says otherwise.

- [ ] **Step 4: Delete the superseded rules from `global.css`**

Remove `.modern-modal-overlay`, `.modern-modal`, `.modern-modal-title`,
`.modern-modal-content`, `.modern-input`, `.modern-input:focus`,
`.modern-button`, `.modern-button-primary`, `.modern-button-secondary`,
`.modern-button:disabled`, `.modern-modal-actions`, `.modern-error`, and
`.modern-button-danger` with its hover.

- [ ] **Step 5: Objective checks**

```bash
cd web_ui && npm run build
```

Expected: `Compiled successfully.`

```bash
cd web_ui && grep -rn "modern-button\|modern-input" src/
```

Expected: no output. Every one of those class names is retired; only
`modern-modal*` and `modern-error` survive, in `MyBrandsPanel.css` and the
markup.

```bash
cd web_ui && grep -c "modern-" src/styles/global.css
```

Expected: `0`.

```bash
cd web_ui && grep -n "ff3b30\|d70015\|007aff" src/components/MyBrandsPanel.css src/components/MyBrandsPanel.js
```

Expected: no output. The old blue and the two old reds are gone from this page
entirely.

- [ ] **Step 6: Visual check**

1. Click `+ ADD BRAND`. The dialog is a flat white square box with a hairline
   border and no blur behind it — the page behind is dimmed, still readable, not
   frosted. The title is small uppercase letterspaced over a hairline rule.
2. The URL field is square; focusing it turns the border black.
3. `CANCEL` is a hairline box; `ADD BRAND` is filled black. With the field empty,
   `ADD BRAND` is visibly disabled — pale text, border intact. If it instead
   looks identical to its enabled state, add `opacity: 0.5` to a
   `.ar-btn:disabled` override in `MyBrandsPanel.css` and note it.
4. Submit a deliberately invalid URL such as `not-a-url`. The error appears as
   red text inside a square red hairline box — no pink fill, no rounding.
5. Cancel out. Click `REMOVE`, select a brand, then the red button. The confirm
   dialog lists the brands as small uppercase em-dashed lines, `CANCEL` is a
   hairline box and the confirm button is red-bordered, filling red on hover.
6. Press `CANCEL`. Nothing was removed — verify the brand is still in the
   sidebar.

Only run the destructive path in check 5 as far as the dialog. Do not confirm
unless you are willing to lose that brand's scraped products.

- [ ] **Step 7: Commit**

```bash
git add web_ui/src/components/MyBrandsPanel.css web_ui/src/components/MyBrandsPanel.js web_ui/src/styles/global.css
git commit -m "Convert the My Brands dialogs

The modern-modal family loses its 12px radius, glass fill, large shadow
and backdrop blur for a flat white box behind a hairline. Titles drop
from 30px to 11px uppercase; the blue primary button becomes the black
fill, and the red confirm becomes a red-bordered button that fills on
hover.

MyBrandsPanel was the family's only consumer, so the rules move into its
stylesheet rather than staying in global.css. MacModal.js is a separate
component with no consumers at all and is left alone.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---
### Task 6: Rebuild Favourites

The largest task, and the only one that changes a page's shape rather than its
surface. Favourites goes from a fixed 50/50 split to the High Fashion anatomy:
sidebar, main area, `SINGLE`/`GRID` toggle, thumb strip, status bar.

The whole component is rewritten, so this is one task rather than two — a
half-rewritten component is not a state worth committing or reviewing.

**Files:**
- Create: `web_ui/src/components/FavouritesPanel.css`
- Modify: `web_ui/src/components/FavouritesPanel.js` (complete rewrite)

**Interfaces:**
- Consumes: the tokens and `.ar-sidebar`, `.ar-sidebar-scroll`,
  `.ar-section-header`, `.ar-list-item`, `.ar-chip`, `.ar-btn`,
  `.ar-status-bar`, `.ar-scroll`, `.ar-empty`, `.ar-loading` from Task 1;
  `TopBar` and the four chrome props from Task 2; `groupMode` from Task 2.
- Consumes from the API, unchanged: `getFavourites()`, `getFavouriteStats()`,
  `removeFavourite(seasonUrl, collectionUrl, lookNumber)`, `getImageUrl(path)`.
  A favourite is `{ id, date_added, image_path, collection: { designer, url },
  season: { name, url }, look: { number, total } }`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Read the file you are replacing**

Read `web_ui/src/components/FavouritesPanel.js` end to end before writing
anything. The rewrite must keep every behaviour it has: loading and empty states,
the two grouping modes, removal, and previous/next cycling that wraps at both
ends. Note that `removeFavourite` takes three arguments in a fixed order —
`season.url`, `collection.url`, `look.number` — and that `loadStats()` is called
again after a successful removal.

- [ ] **Step 2: Write the stylesheet**

Create `web_ui/src/components/FavouritesPanel.css`:

```css
/* Favourites — the archive language. Tokens live in styles/archive.css.
   The anatomy deliberately mirrors HighFashionV2: same sidebar width, same
   thumb dimensions, same toggle, so moving between the two pages does not
   feel like moving between two apps.

   The page shell is .ar-page + .ar-content from styles/archive.css — the same
   two classes My Brands uses. */

/* --- Sidebar ------------------------------------------------------- */

.fav-mode-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0 2px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--ar-line);
  flex-shrink: 0;
}

/* The season is what tells two rows of the same designer apart, so it gets
   its own line rather than being truncated off the end of a shared one. */
.fav-collection .num {
  width: 32px;
  flex-shrink: 0;
  font-size: 11px;
  line-height: 16px;
  color: var(--ar-ink-4);
}

.fav-collection.selected .num {
  color: var(--ar-ink-3);
}

.fav-collection .body {
  flex: 1;
  min-width: 0;
}

.fav-collection .name {
  display: block;
  line-height: 16px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.fav-collection .sub {
  display: block;
  font-size: 10px;
  line-height: 13px;
  color: var(--ar-ink-4);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.fav-collection:hover .sub,
.fav-collection.selected .sub {
  color: var(--ar-ink-3);
}

/* --- Main ---------------------------------------------------------- */

.fav-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--ar-bg);
  overflow: hidden;
}

.fav-controls {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 12px 24px;
  flex-shrink: 0;
}

.fav-view-toggle {
  display: flex;
  gap: 1px;
  background: var(--ar-line);
  padding: 1px;
}

.fav-view-toggle .ar-btn {
  border: none;
  padding: 7px 16px;
}

/* --- Single view --------------------------------------------------- */

.fav-single {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.fav-single-content {
  flex: 1;
  position: relative;
  display: flex;
  align-items: stretch;
  justify-content: center;
  min-height: 0;
  padding: 0 40px 24px;
}

.fav-image-side {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-width: 0;
  height: 100%;
}

.fav-image-frame {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
  width: 100%;
}

.fav-image-frame img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.fav-image-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  max-width: 520px;
  padding: 0 4px;
}

.fav-look-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.15em;
  color: var(--ar-ink);
}

.fav-look-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.fav-added {
  font-size: 10px;
  color: var(--ar-ink-4);
  letter-spacing: 0.05em;
}

/* Unfavouriting is reversible — the look is still in the archive — so this
   is a plain control that only reddens on hover. */
.fav-remove {
  padding: 5px 12px;
  font-size: 10px;
}

.fav-remove:hover {
  border-color: var(--ar-danger);
  color: var(--ar-danger);
}

.fav-arrow {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 40px;
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  font-family: inherit;
  font-size: 24px;
  color: var(--ar-ink-4);
  cursor: pointer;
  transition: color 0.15s ease;
  z-index: 10;
}

.fav-arrow:hover {
  color: var(--ar-ink);
}

.fav-arrow.prev { left: 0; }
.fav-arrow.next { right: 0; }

/* --- Thumb strip --------------------------------------------------- */

.fav-thumb-strip-container {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  overflow: hidden;
  border-top: 1px solid var(--ar-line);
  background: var(--ar-bg-sub);
}

.fav-thumb-strip {
  display: flex;
  gap: 8px;
  padding: 16px 24px;
  overflow-x: auto;
  max-width: 100%;
  scrollbar-width: none;
}

.fav-thumb-strip::-webkit-scrollbar {
  display: none;
}

.fav-thumb {
  flex-shrink: 0;
  width: 44px;
  height: 60px;
  cursor: pointer;
  overflow: hidden;
  background: #f5f5f5;
  opacity: 0.5;
  transition: all 0.15s ease;
}

.fav-thumb:hover {
  opacity: 0.8;
}

.fav-thumb.active {
  opacity: 1;
  outline: 2px solid var(--ar-ink);
  outline-offset: -2px;
}

.fav-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* --- Grid view ----------------------------------------------------- */

.fav-grid-container {
  flex: 1;
  overflow-y: auto;
  padding: 0 24px 24px;
  min-height: 0;
}

.fav-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
  align-content: start;
}

.fav-grid-item {
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: transform 0.15s ease;
}

.fav-grid-item:hover {
  transform: translateY(-2px);
}

.fav-grid-image {
  aspect-ratio: 3 / 4;
  overflow: hidden;
  background: #f5f5f5;
  display: flex;
  align-items: center;
  justify-content: center;
}

.fav-grid-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: opacity 0.15s ease;
}

.fav-grid-item:hover .fav-grid-image img {
  opacity: 0.9;
}

.fav-grid-item.selected .fav-grid-image {
  outline: 2px solid var(--ar-ink);
  outline-offset: -2px;
}

.fav-grid-item .look-num {
  font-size: 11px;
  color: var(--ar-ink-3);
  padding: 8px 0;
  text-align: center;
  letter-spacing: 0.1em;
}

.fav-grid-item.selected .look-num {
  color: var(--ar-ink);
  font-weight: 600;
}
```

- [ ] **Step 3: Rewrite the component**

Replace the entire contents of `web_ui/src/components/FavouritesPanel.js` with:

```javascript
import React, { useState, useEffect, useMemo } from 'react';
import TopBar from './TopBar';
import { FashionArchiveAPI } from '../services/api';
import './FavouritesPanel.css';

// The sidebar's first row: every favourite, rather than one collection.
const ALL = '__all__';

function collectionKey(fav) {
  return `${fav.collection.designer}::${fav.season.name}`;
}

function FavouritesPanel({ currentPage, onPageSwitch, currentUser, onLogout }) {
  const [favourites, setFavourites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({});

  // Was App-level state written by the old MenuBar's View menu. It orders
  // the sidebar: RECENT by when a look was saved, BY COLLECTION by designer.
  const [groupMode, setGroupMode] = useState('view-all');
  const [selectedKey, setSelectedKey] = useState(ALL);
  const [viewMode, setViewMode] = useState('single');
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    loadFavourites();
    loadStats();
  }, []);

  const loadFavourites = async () => {
    try {
      setLoading(true);
      const favs = await FashionArchiveAPI.getFavourites();
      setFavourites(favs);
    } catch (error) {
      console.error('FavouritesPanel: Error loading favourites:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async () => {
    try {
      setStats(await FashionArchiveAPI.getFavouriteStats());
    } catch (error) {
      console.error('Error loading stats:', error);
    }
  };

  const collections = useMemo(() => {
    const byKey = new Map();

    favourites.forEach(fav => {
      const key = collectionKey(fav);
      if (!byKey.has(key)) {
        byKey.set(key, {
          key,
          designer: fav.collection.designer,
          season: fav.season.name,
          items: [],
          latest: 0,
        });
      }
      const group = byKey.get(key);
      group.items.push(fav);
      const added = new Date(fav.date_added).getTime();
      if (added > group.latest) group.latest = added;
    });

    const groups = [...byKey.values()];
    groups.forEach(g => g.items.sort((a, b) => a.look.number - b.look.number));
    groups.sort((a, b) => (
      groupMode === 'by-collection'
        ? a.designer.toLowerCase().localeCompare(b.designer.toLowerCase())
        : b.latest - a.latest
    ));
    return groups;
  }, [favourites, groupMode]);

  const visible = useMemo(() => {
    if (selectedKey !== ALL) {
      const group = collections.find(g => g.key === selectedKey);
      return group ? group.items : [];
    }

    const all = [...favourites];
    if (groupMode === 'by-collection') {
      all.sort((a, b) => {
        const byDesigner = a.collection.designer.toLowerCase()
          .localeCompare(b.collection.designer.toLowerCase());
        return byDesigner !== 0 ? byDesigner : a.look.number - b.look.number;
      });
    } else {
      all.sort((a, b) => new Date(b.date_added) - new Date(a.date_added));
    }
    return all;
  }, [favourites, collections, selectedKey, groupMode]);

  // Keep the cursor inside the list after a removal shrinks it.
  useEffect(() => {
    setSelectedIndex(i => (visible.length === 0 ? 0 : Math.min(i, visible.length - 1)));
  }, [visible.length]);

  const handleSelectCollection = (key) => {
    setSelectedKey(key);
    setSelectedIndex(0);
  };

  const handleGroupMode = (mode) => {
    setGroupMode(mode);
    setSelectedIndex(0);
  };

  const handlePrev = () => {
    if (visible.length === 0) return;
    setSelectedIndex(i => (i > 0 ? i - 1 : visible.length - 1));
  };

  const handleNext = () => {
    if (visible.length === 0) return;
    setSelectedIndex(i => (i < visible.length - 1 ? i + 1 : 0));
  };

  const handleRemove = async (favourite) => {
    try {
      const result = await FashionArchiveAPI.removeFavourite(
        favourite.season.url,
        favourite.collection.url,
        favourite.look.number
      );
      if (result.success) {
        setFavourites(prev => prev.filter(f => f.id !== favourite.id));
        loadStats();
      }
    } catch (error) {
      console.error('Error removing favourite:', error);
    }
  };

  const chrome = (
    <TopBar
      currentPage={currentPage}
      onPageSwitch={onPageSwitch}
      currentUser={currentUser}
      onLogout={onLogout}
    />
  );

  if (loading) {
    return (
      <div className="ar-page">
        {chrome}
        <div className="ar-loading">
          <span className="headline">Loading favourites</span>
        </div>
      </div>
    );
  }

  if (favourites.length === 0) {
    return (
      <div className="ar-page">
        {chrome}
        <div className="ar-empty">
          <span className="headline">No favourites</span>
          <span>Open a collection and save a look to see it here</span>
        </div>
      </div>
    );
  }

  const current = visible[selectedIndex] || null;

  return (
    <div className="ar-page">
      {chrome}

      <div className="ar-content">
        <div className="ar-sidebar">
          <div className="fav-mode-row">
            <button
              className={`ar-chip ${groupMode === 'view-all' ? 'selected' : ''}`}
              onClick={() => handleGroupMode('view-all')}
            >Recent</button>
            <button
              className={`ar-chip ${groupMode === 'by-collection' ? 'selected' : ''}`}
              onClick={() => handleGroupMode('by-collection')}
            >By collection</button>
          </div>

          <div className="ar-section-header">
            <span>Collections</span>
            <span className="count">{collections.length}</span>
          </div>

          <div className="ar-sidebar-scroll ar-scroll">
            <div
              className={`ar-list-item fav-collection ${selectedKey === ALL ? 'selected' : ''}`}
              onClick={() => handleSelectCollection(ALL)}
            >
              <span className="num">—</span>
              <span className="body">
                <span className="name">All favourites</span>
                <span className="sub">{favourites.length} looks</span>
              </span>
            </div>

            {collections.map((group, idx) => (
              <div
                key={group.key}
                className={`ar-list-item fav-collection ${group.key === selectedKey ? 'selected' : ''}`}
                onClick={() => handleSelectCollection(group.key)}
              >
                <span className="num">{String(idx + 1).padStart(3, '0')}</span>
                <span className="body">
                  <span className="name">{group.designer}</span>
                  <span className="sub">{group.season} · {group.items.length}</span>
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="fav-main">
          <div className="fav-controls">
            <div className="fav-view-toggle">
              <button
                className={`ar-btn ${viewMode === 'single' ? 'active' : ''}`}
                onClick={() => setViewMode('single')}
              >Single</button>
              <button
                className={`ar-btn ${viewMode === 'grid' ? 'active' : ''}`}
                onClick={() => setViewMode('grid')}
              >Grid</button>
            </div>
          </div>

          {visible.length === 0 ? (
            <div className="ar-empty">
              <span className="headline">Nothing in this collection</span>
            </div>
          ) : viewMode === 'grid' ? (
            <div className="fav-grid-container ar-scroll">
              <div className="fav-grid">
                {visible.map((fav, idx) => (
                  <div
                    key={fav.id}
                    className={`fav-grid-item ${idx === selectedIndex ? 'selected' : ''}`}
                    onClick={() => { setSelectedIndex(idx); setViewMode('single'); }}
                  >
                    <div className="fav-grid-image">
                      <img
                        src={FashionArchiveAPI.getImageUrl(fav.image_path)}
                        alt={`Look ${fav.look.number}`}
                        loading="lazy"
                      />
                    </div>
                    <span className="look-num">{String(fav.look.number).padStart(2, '0')}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : current ? (
            <div className="fav-single">
              <div className="fav-single-content">
                {visible.length > 1 && (
                  <button className="fav-arrow prev" onClick={handlePrev}>‹</button>
                )}

                <div className="fav-image-side">
                  <div className="fav-image-frame">
                    <img
                      src={FashionArchiveAPI.getImageUrl(current.image_path)}
                      alt={`Look ${current.look.number}`}
                      onError={(e) => {
                        e.target.alt = 'Image not found';
                        e.target.style.background = '#f5f5f5';
                      }}
                    />
                  </div>
                  <div className="fav-image-info">
                    <span className="fav-look-label">
                      LOOK {String(current.look.number).padStart(2, '0')}
                    </span>
                    <span className="fav-look-meta">
                      <span className="fav-added">
                        Added {new Date(current.date_added).toLocaleDateString()}
                      </span>
                      <button
                        className="ar-btn fav-remove"
                        onClick={() => handleRemove(current)}
                      >Remove</button>
                    </span>
                  </div>
                </div>

                {visible.length > 1 && (
                  <button className="fav-arrow next" onClick={handleNext}>›</button>
                )}
              </div>

              <div className="fav-thumb-strip-container">
                <div className="fav-thumb-strip">
                  {visible.map((fav, idx) => (
                    <div
                      key={fav.id}
                      className={`fav-thumb ${idx === selectedIndex ? 'active' : ''}`}
                      onClick={() => setSelectedIndex(idx)}
                    >
                      <img
                        src={FashionArchiveAPI.getImageUrl(fav.image_path)}
                        alt={`Look ${fav.look.number}`}
                        loading="lazy"
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}

          <div className="ar-status-bar">
            <span>
              {current
                ? <>{current.collection.designer} / <span className="active">{current.season.name}</span></>
                : `${stats.total_favourites || favourites.length} looks`}
            </span>
            <span>
              {current && (
                <>LOOK <span className="active">{String(current.look.number).padStart(2, '0')}</span> / {visible.length}</>
              )}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default FavouritesPanel;
```

The status bar sits inside `.fav-main` rather than being `position: fixed` with
`left: 280px` as High Fashion's is. It lines up in the same place, because the
main column already starts after the sidebar, and an in-flow element cannot drift
out of alignment if the sidebar width ever changes.

- [ ] **Step 4: Objective checks**

```bash
cd web_ui && npm run build
```

Expected: `Compiled successfully.`

```bash
cd web_ui && grep -n "mac-panel\|mac-button\|mac-title-bar\|columns-container\|mac-scrollbar\|gallery-item\|style={{" src/components/FavouritesPanel.js
```

Expected: no output. Every old class and every inline style object is gone — the
rewrite moved all of it into the stylesheet.

```bash
cd web_ui && grep -c "currentView" src/components/FavouritesPanel.js
```

Expected: `0`.

```bash
cd web_ui && grep -n "removeFavourite" src/components/FavouritesPanel.js
```

Expected: one hit, passing `favourite.season.url`, `favourite.collection.url`,
`favourite.look.number` in that order. A reordering here silently removes the
wrong favourite, so read the three arguments rather than trusting the diff.

- [ ] **Step 5: Visual check**

You need at least two favourited looks across at least two collections. If the
account has none, favourite a few from High Fashion first.

1. The page is sidebar + main, matching High Fashion's proportions — the sidebar
   is the same width and the same `#fafafa`.
2. Sidebar top holds two chips, `RECENT` and `BY COLLECTION`. The active one is
   bold black with a black bar on its left edge.
3. Under `COLLECTIONS` and its count sits `ALL FAVOURITES` with a total, then one
   row per collection: a three-digit index, the designer, and the season with a
   count on a second line in paler grey.
4. Switch to `BY COLLECTION` — the sidebar reorders alphabetically by designer.
   Switch back to `RECENT` — the most recently saved collection returns to the
   top.
5. Click a collection: the main area narrows to its looks and the row takes the
   black left bar.
6. `SINGLE` shows one large image, `LOOK NN` at the left of the info line, the
   added date and a `REMOVE` button at the right, and a thumb strip beneath with
   the current thumb outlined black.
7. `‹` and `›` at the left and right edges move between looks, wrapping at both
   ends. They are pale grey and blacken on hover. With only one look visible they
   are absent.
8. `GRID` shows 3/4 tiles with look numbers; clicking one selects it and returns
   to `SINGLE` on that look.
9. The status bar along the bottom of the main area reads `DESIGNER / SEASON` at
   the left, `LOOK NN / total` at the right, with the season and number in black.
10. `REMOVE` removes the look. The list closes up, the status bar total drops by
    one, and the view stays on a valid look rather than going blank. Remove the
    last look in a collection and the sidebar row disappears.
11. Sign in with an account that has no favourites, or remove them all: the page
    shows `NO FAVOURITES` in pale grey with one line beneath. No emoji, no
    bordered card.
12. Nothing anywhere is pixel type, blue, or rounded.

- [ ] **Step 6: Commit**

```bash
git add web_ui/src/components/FavouritesPanel.js web_ui/src/components/FavouritesPanel.css
git commit -m "Rebuild Favourites on the High Fashion anatomy

Favourites was a fixed 50/50 split with no sidebar and no view toggle,
so it read as a different app from the viewer next to it. It now has the
same parts in the same places: 280px sidebar, SINGLE/GRID toggle, thumb
strip, status bar.

The old View menu's two modes become the sidebar's chip row, ordering
collections by when a look was saved or by designer. Selecting a
collection narrows the main area to it; ALL FAVOURITES is the first row.

Behaviour is preserved: both grouping modes, removal, and previous/next
cycling that wraps at both ends. The status bar sits in the main column
rather than being fixed at left:280px, so it cannot drift out of
alignment if the sidebar width changes.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: The product detail drawer

Reached by clicking a tile in My Brands, so leaving it in the old language would
make the page visibly half-converted. Mechanical: a long stylesheet, moved and
rewritten, with almost no markup change.

**Files:**
- Create: `web_ui/src/components/ProductDetailPanel.css`
- Modify: `web_ui/src/components/ProductDetailPanel.js`
- Modify: `web_ui/src/styles/global.css` (remove the `.detail-*` and `.carousel-*` rules)

**Interfaces:**
- Consumes: the tokens from Task 1.
- Produces: nothing.

- [ ] **Step 1: Inventory what you are converting**

```bash
cd web_ui && grep -n "^\.detail-\|^\.carousel-\|^\.s-" src/styles/global.css
```

Every rule that prints belongs in the new stylesheet. Read them all before
writing, and read `ProductDetailPanel.js` for the class names in use — the list
includes `detail-panel-wrapper`, `detail-resize-handle`, `product-detail-panel`,
`detail-panel-header`, `detail-panel-close`, the `detail-carousel*` and
`carousel-*` family, `detail-info`, `detail-brand`, `detail-name`,
`detail-breadcrumb*`, `detail-price*`, `detail-tag*`, `detail-block`,
`detail-section-head`, `detail-size-grid`, `s-label`, `s-meta`,
`detail-description`, `detail-composition*`.

- [ ] **Step 2: Write the stylesheet**

Create `web_ui/src/components/ProductDetailPanel.css`. Convert each rule you
inventoried, applying the global constraints rather than inventing new values:

- Every `var(--macos-text)` becomes `var(--ar-ink)`; `var(--macos-text-secondary)`
  becomes `var(--ar-ink-3)`; `var(--macos-border)` becomes `var(--ar-line)`;
  `var(--macos-bg)` becomes `#f5f5f5` on image grounds and `var(--ar-bg)`
  elsewhere; `var(--macos-accent)` becomes `var(--ar-ink)`.
- Every `border-radius` becomes `0`. `.carousel-dot` is the one exception worth
  thinking about: a square 6px dot is unreadable, so drop the dots' radius to `0`
  and make them 6px squares, pale grey and black when active.
- Every `font-size` comes down to the scale: `.detail-brand` 21px → 9px uppercase
  `0.15em` in `--ar-ink-3`; `.detail-name` → 13px `--ar-ink`; `.detail-price` →
  12px `--ar-ink` 600; `.detail-section-head` → 10px uppercase `0.15em`
  `--ar-ink-3` above a `1px solid var(--ar-line)`; body copy and breadcrumbs →
  11px.
- `.detail-panel-close` goes from 36px to a 16px `×` in `--ar-ink-3`, blackening
  on hover.
- `.carousel-arrow` loses its translucent white fill for transparent, with the
  glyph in `--ar-ink-4` blackening on hover, matching `.fav-arrow`.
- `.detail-tag-promo`, `.detail-tag-bad` and `.detail-tag-good` all become
  hairline outlined 9px uppercase chips in `--ar-ink-2`, exactly like the tile
  badges. None is filled and none is coloured.
- `.detail-resize-handle:hover` goes from blue to `background: var(--ar-ink)` at
  full opacity, and the handle keeps its 5px width and `col-resize` cursor.
- `.product-detail-panel` keeps `border-left: 1px solid var(--ar-line)` and
  `background: var(--ar-bg)`, drops any radius and shadow, and its height changes
  from `calc(100vh - 40px)` to `100%` — it now sits inside the flex column from
  Task 2 rather than under fixed chrome. `.detail-panel-wrapper` changes the same
  way.

- [ ] **Step 3: Import it**

Add to `web_ui/src/components/ProductDetailPanel.js`, after the React import:

```javascript
import './ProductDetailPanel.css';
```

- [ ] **Step 4: Soften the close glyph**

The close button renders `&times;`. Leave the character; the stylesheet resizes
it. No markup change is needed unless Step 2's sizing leaves it misaligned, in
which case add `line-height: 1` to `.detail-panel-close` rather than changing the
JSX.

- [ ] **Step 5: Delete the old rules from `global.css`**

Remove every rule from the Step 1 inventory.

- [ ] **Step 6: Objective checks**

```bash
cd web_ui && npm run build
```

Expected: `Compiled successfully.`

```bash
cd web_ui && grep -c "^\.detail-\|^\.carousel-" src/styles/global.css
```

Expected: `0`.

```bash
cd web_ui && grep -n "macos-\|VT323\|border-radius: [1-9]" src/components/ProductDetailPanel.css
```

Expected: no output.

```bash
cd web_ui && grep -c "detail-" src/components/ProductDetailPanel.css
```

Expected: a number above 20 — the rules moved rather than being dropped. If this
is near zero the stylesheet is incomplete and the drawer will be unstyled.

- [ ] **Step 7: Visual check**

Open My Brands, select a category, click a product:

1. The drawer opens against a hairline left border, square, with no shadow.
2. Brand is small grey uppercase above a 13px black product name. The price is
   12px black, with any struck-through original beside it in pale grey.
3. Stock and promo tags are outlined 9px uppercase chips — none filled, none
   coloured.
4. Section headings (`COLOR`, `SIZE`, `DESCRIPTION`, `MATERIAL COMPOSITION`) are
   10px uppercase letterspaced grey above hairlines.
5. The carousel arrows appear on hover as pale glyphs that blacken; dots are
   small squares, the active one black; thumbnails take a black border when
   active.
6. Drag the resize handle — it turns black while dragged and the drawer resizes.
7. The close `×` is small and grey, blackening on hover, and closes the drawer.
8. Nothing in the drawer is pixel type, blue, or rounded.

- [ ] **Step 8: Commit**

```bash
git add web_ui/src/components/ProductDetailPanel.css web_ui/src/components/ProductDetailPanel.js web_ui/src/styles/global.css
git commit -m "Convert the product detail drawer

The drawer opens from a My Brands tile, so leaving it in the old
language would have made that page half-converted. Type comes down to
the scale, radius and shadow go, stock and promo tags become outlined
chips rather than filled colour, and the resize handle turns black
rather than blue.

Its rules move out of global.css into a stylesheet beside the component,
following TopBar.css and HighFashionV2.css.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Sweep and verify

The last task exists because the previous seven each verified their own page in
isolation. This one checks the claim the whole change is making — that the three
pages are one app — and clears what the conversion orphaned.

**Files:**
- Modify: `web_ui/src/styles/global.css`
- Modify: `docs/superpowers/specs/2026-09-11-favourites-mybrands-design-language-design.md`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: nothing.

- [ ] **Step 1: Remove the marquee rules**

`App.js` was the only consumer of `.marquee-track` and `.marquee-item`, and Task
2 deleted that markup. Confirm, then delete both rules from `global.css`:

```bash
cd web_ui && grep -rn "marquee" src/ --include=*.js
```

Expected: no output before you delete anything. If `App.js` still mentions it,
stop — Task 2 was not finished.

- [ ] **Step 2: Do not delete the `mac-*` and `gallery-*` rules**

They look orphaned now and they are not.

```bash
cd web_ui && grep -rln "mac-panel\|mac-button\|gallery-item" src/ --include=*.js
```

Expected: `CollectionsPanel.js`, `SeasonsPanel.js`, `ImageViewerPanel.js`,
`VideoModal.js` and `MenuBar.js`. Those components still reference them, so the
rules stay.

Worth knowing, and out of scope here: `SeasonsPanel`, `CollectionsPanel` and
`ImageViewerPanel` are imported by `App.js` but never rendered — the render tree
only reaches `HighFashionV2`, `FavouritesPanel`, `MyBrandsPanel`, `VideoWindow`
and `AuthPanel`. The old language is being kept alive by components that no
longer appear on screen. Removing that dead code would let `global.css` lose the
`mac-*` and `gallery-*` families outright, but it is a separate change with its
own risk. Do not start it here. Report it.

- [ ] **Step 3: Whole-app objective checks**

```bash
cd web_ui && npm run build
```

Expected: `Compiled successfully.` Compare the warning list against `git stash`-
free `master` if you are unsure whether a warning predates this work.

```bash
cd web_ui && grep -n "VT323\|007aff\|macos-accent\|ff3b30\|b00020\|b85c00\|backdrop-filter" \
  src/components/FavouritesPanel.css src/components/FavouritesPanel.js \
  src/components/MyBrandsPanel.css src/components/MyBrandsPanel.js \
  src/components/ProductDetailPanel.css src/styles/archive.css
```

Expected: no output. This is the single check that the two pages carry none of
the old language.

```bash
cd web_ui && wc -l src/styles/global.css
```

Expected: meaningfully below the 1882 lines it started at. Record the number in
the commit message.

```bash
cd web_ui && grep -rn "class.*hf2-" src/components/FavouritesPanel.js src/components/MyBrandsPanel.js
```

Expected: no output. The two pages use the shared `.ar-*` primitives, not High
Fashion's private classes — borrowing `hf2-` names would couple them to a file
this change promised not to touch.

- [ ] **Step 4: Side-by-side visual check**

This is the one that decides whether the work succeeded. Open each page in turn
and compare against High Fashion:

1. Same top bar, same height, same active-link treatment.
2. Same sidebar width, same `#fafafa`, same hairline against the main area.
3. Same section-header treatment: 10px, uppercase, letterspaced, grey.
4. Same selection: bold black, 2px black left border, faint wash. No blue on any
   page, in any state, including hover and focus.
5. Same type: monospace throughout, nothing above 13px.
6. Same edges: no rounded corner, no shadow, no blur anywhere.
7. Same scrollbars: thin, square, pale.
8. Switch between the three pages repeatedly. Nothing should jump, resize or
   reflow at the top — the chrome is identical, so the pages should feel like
   tabs of one app.

- [ ] **Step 5: Record the outcome in the spec**

Change the spec's `Status:` line from `approved, not yet implemented` to
`implemented <date>`, and add a short section at the end recording anything that
came out differently from the design — the Favourites status bar being in-flow
rather than fixed, whatever the visual checks turned up, and the dead-component
finding from Step 2. Write what is true, including anything left unfinished.

- [ ] **Step 6: Commit**

```bash
git add web_ui/src/styles/global.css docs/superpowers/specs/2026-09-11-favourites-mybrands-design-language-design.md
git commit -m "Drop the marquee rules and record the outcome

App.js was the marquee's only consumer and its markup went with the old
chrome.

The mac-* and gallery-* families stay: CollectionsPanel, SeasonsPanel,
ImageViewerPanel, VideoModal and MenuBar still reference them. Those
first three are imported by App.js but never rendered, so the old
language is kept alive by components that no longer appear on screen —
worth removing, but as its own change.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Notes for whoever executes this

**Report honestly.** Every task has two gates and both matter. A clean `npm run
build` proves the CSS parses, not that the page looks right — it cannot tell you
a sidebar is 27px pixel type. If a visual check fails, say which number failed
and what you saw. If you could not run a check — no favourites on the account, no
brand you were willing to remove — say that rather than marking it passed.

**Do not widen the change.** Several things you will pass are worth fixing and
are not this: the three unrendered panels, `MacModal.js` having no consumers,
`MenuBar.js`'s three orphaned tools, `global.css` still being large. Note them,
leave them.

**If a step is wrong, say so.** This plan was written from reading the code, not
from running it. If `MyBrandsPanel.js`'s line numbers have moved, or a selector
turns out to have a consumer this plan claims it does not, trust what you find
over what you read here — then say what differed.
