# Phase 2: Persistence, loading behaviour, and naming — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The app stops forgetting things. Refreshing returns you where you were, preferences survive, changing a filter no longer throws away the show you are looking at, and a loading collection shows itself growing instead of blanking the screen.

**Architecture:** Four shared hooks and one label module. `usePersistentState` generalises the one localStorage key that already exists. `useCollectionImages` takes the image-streaming state out of `HighFashionPage` and gives it keep-previous and ghost-slot behaviour. `lookLabel` becomes the single place that decides what an image is called.

**Tech Stack:** React 18, Create React App (`react-scripts` 5), Jest + `@testing-library/react`, plain CSS with custom properties.

## Global Constraints

- **No new npm dependencies.** `@testing-library/react` and `@testing-library/jest-dom` were added at the end of phase 1 and are available.
- **`archive.css` must be imported before `App` in `src/index.js`.** `npm run check:css` asserts it against the built bundle. It now matches rule starts, so both pairs are real.
- **`react-scripts build` is the lint gate.** With `CI=true` its warnings are errors. Do not add `eslint-disable` to silence something you have not understood; the two existing suppressions carry written reasons.
- **`removeFavourite(seasonUrl, collectionUrl, lookNumber)` is positional.** Two of three arguments are URLs. Reordering them deletes the wrong favourite silently. Phase 3 owns that call; do not touch it here.
- **The look NUMBER is database identity and does not change.** It is part of the unique index on `favourites`. Only the label changes.
- **Commit after every task.** Never `--no-verify`. Branch `master`, commit locally, do not push — pushing master is a deploy.
- Run npm commands from `web_ui/`. Node 20.19.6.
- The Write/Edit tools in this environment wrongly believe the session is in a deleted git worktree. Use Bash for file changes.

## Starting state

Phase 1 left the tree as `src/{app,features,shared}/` with 133 passing tests in 6 suites. Relevant facts, verified:

- **Only one preference is persisted:** `hf2-sidebar`, read at `HighFashionPage.js:124` and written at `:133`.
- Preferences that are NOT persisted: `viewMode` (`HighFashionPage.js:189`), `sortBy` and `detailPanelWidth` (`BrandsPage.js:32,41`), `groupMode` and `viewMode` (`LibraryPage.js:23,25`).
- **Four sites clear the open show when the filter set changes** — around `HighFashionPage.js:316`, `:332`, `:426`, `:436`. Each does `setSelectedCollection(null); setCollections([]); setImages([]); setExpectedLookCount(0)`.
- **Opening a show blanks the screen** at `HighFashionPage.js:662`: `setImages([]); setCurrentImageIndex(0); setImagesLoading(true)`.
- **The expected total is already on the wire.** `streamCollectionImages`'s `onMeta` supplies `meta.count` into `expectedLookCount` (`:706`). No backend change is needed for the growing indicator.
- The word "LOOK" appears in `Viewer.js`, `StatusBar.js` and `LibraryPage.js`.

Read the files before you edit them — line numbers drift as tasks land.

---

### Task 1: `usePersistentState`

**Files:**
- Create: `web_ui/src/shared/hooks/usePersistentState.js`
- Test: `web_ui/src/shared/hooks/usePersistentState.test.js`

**Interfaces:**
- Produces: `usePersistentState(key, initialValue, options?) -> [value, setValue]`. Signature matches `useState`, including the functional-update form of the setter. `options.serialize` / `options.deserialize` default to JSON. The key is namespaced with a module-level prefix so the app's keys cannot collide with anything else on the origin.

**Behaviour this must have, each of which is a test:**

- Returns `initialValue` when nothing is stored.
- Returns the stored value when there is one.
- Writing updates both the state and localStorage.
- The functional-update form works: `setValue(v => v + 1)`.
- `initialValue` may be a function (lazy initialiser), matching `useState`.
- **A corrupt stored value falls back to `initialValue` instead of throwing.** Store the literal string `{not json` under the key and confirm the hook returns the initial value and does not throw. This is the one that matters: a user whose storage holds a half-written value from an old release must not get a white screen.
- **A `localStorage` that throws is survivable.** Safari private mode throws on `setItem`; some browsers throw on read. Stub `window.localStorage.getItem` and `setItem` to throw and confirm the hook still returns and updates in-memory state. The feature degrades to not-remembered; it does not break the page.
- Two hooks with different keys do not interfere.

- [ ] **Step 1: Write the failing tests.** Use `@testing-library/react`'s `renderHook`. Clear `localStorage` in `beforeEach`. Restore any stubbed global in `afterEach`.
- [ ] **Step 2: Run them, confirm they fail** — `cd web_ui && CI=true npx react-scripts test --watchAll=false --testPathPattern="usePersistentState"`
- [ ] **Step 3: Implement.** Reads happen once, in a lazy `useState` initialiser — not on every render. Writes happen in an effect keyed on the value. Wrap every storage call in try/catch.
- [ ] **Step 4: Run them, confirm they pass.**
- [ ] **Step 5: Commit.**

---

### Task 2: `lookLabel`, and the end of the word "look"

**Files:**
- Create: `web_ui/src/shared/lib/lookLabel.js`
- Test: `web_ui/src/shared/lib/lookLabel.test.js`
- Modify: `src/features/high-fashion/Viewer.js`, `StatusBar.js`, `src/features/library/LibraryPage.js`

**Interfaces:**
- Produces:
  - `lookLabel(number) -> string` — the label for one image. Returns the zero-padded number alone, e.g. `'07'`.
  - `lookCounter(number, total) -> string` — the status-bar form, e.g. `'07 / 38'`.
  - `lookAlt(number, designer?) -> string` — the `alt` text, which still needs words because it is read aloud.

**Why:** `extractLookNumber` parses the number out of the image filename and falls back to the array index. Detail shots and back views inflate it, so a collection's "LOOK 34" is frequently not that designer's thirty-fourth look. The number is the identity of every saved favourite and cannot change; the word is a claim the data does not support, so it goes.

**Behaviour, each a test:**
- `lookLabel(7)` is `'07'`; `lookLabel(34)` is `'34'`; `lookLabel(107)` is `'107'` — padding to two digits, never truncating a third.
- `lookCounter(7, 38)` is `'07 / 38'`.
- `lookLabel(null)` and `lookLabel(undefined)` return `''` rather than `'0NaN'`.
- `lookAlt(7)` contains a word — it is alt text, not a bare number.
- `lookAlt(7, 'Gucci')` names the designer.

- [ ] **Step 1: Write the failing tests.**
- [ ] **Step 2: Run them, confirm they fail.**
- [ ] **Step 3: Implement the module.**
- [ ] **Step 4: Replace every user-visible use of the word.** Grep `grep -rn "LOOK \|Look " web_ui/src --include="*.js"`. Each call site uses `lookLabel` / `lookCounter` / `lookAlt`. Do NOT change any variable, prop or function name containing "look" — `lookNumber`, `extractLookNumber`, `currentLookNumber` stay. This is a label change, not a rename.
- [ ] **Step 5: Confirm nothing user-facing says "LOOK"** — `grep -rn "LOOK " web_ui/src --include="*.js"` returns nothing outside `lookLabel.js`'s own tests and alt text.
- [ ] **Step 6: Build, test, `check:css`.**
- [ ] **Step 7: Commit.** Say in the message that the number is database identity and only the label moved.

---

### Task 3: Persist the five preferences

**Files:**
- Modify: `src/features/high-fashion/HighFashionPage.js`, `src/features/brands/BrandsPage.js`, `src/features/library/LibraryPage.js`

**Interfaces:** consumes `usePersistentState` from Task 1.

| Preference | File | Current | Key |
|---|---|---|---|
| sidebar open | `HighFashionPage.js:122` | already persisted, hand-rolled | keep its existing stored value readable |
| view mode | `HighFashionPage.js:189` | not persisted | new |
| sort order | `BrandsPage.js:32` | not persisted | new |
| detail panel width | `BrandsPage.js:41` | not persisted | new |
| group mode | `LibraryPage.js:23` | not persisted | new |
| library view mode | `LibraryPage.js:25` | not persisted | new |

- [ ] **Step 1: Replace the hand-rolled sidebar persistence** with `usePersistentState`. **Migration matters:** the existing key is `hf2-sidebar` and its stored values are the strings `'closed'` / `'open'`, not JSON booleans. A user with `'closed'` stored must still open to a collapsed sidebar. Either keep reading that exact format via the `deserialize` option, or read-and-migrate once. Write a test for the migration — a stored `'closed'` must produce a closed sidebar.
- [ ] **Step 2: Persist the other five.** Each is a one-line change from `useState` to `usePersistentState` with a key.
- [ ] **Step 3: Clamp what comes back.** A stored `viewMode` of `'gird'` (or anything a future version stops supporting) must not render a blank pane. Each restored value is validated against the set of values the component actually handles, falling back to the default. Test one.
- [ ] **Step 4:** `detailPanelWidth` is a number used in a style. A stored value of `0`, a negative, or something absurd must be clamped to the same bounds the drag handler enforces. Find those bounds in `BrandsPage.js` and reuse them rather than inventing new ones. Test the clamp.
- [ ] **Step 5: Build, full suite, `check:css`.**
- [ ] **Step 6: Commit.**

---

### Task 4: Changing a filter stops closing the show

**Files:** Modify `src/features/high-fashion/HighFashionPage.js`

The four sites listed in Starting state each clear the collection list AND the open show. Clearing the list is right — the list is a window on a filtered query and must refetch. Clearing the show is not: the user narrowed the list beside the thing they were looking at, and the thing they were looking at vanished.

- [ ] **Step 1: Find all four sites.** `grep -n "setCollections(\[\])" src/features/high-fashion/HighFashionPage.js`. Read each one's surrounding function — they are not all the same trigger (a filter change, a designer-mode entry, a clear, a search). Decide per site whether closing the show is right there. **Entering designer mode is a different act from narrowing a filter** — judge it on its own and say what you decided in your report.
- [ ] **Step 2: For the filter-change sites, stop clearing `selectedCollection`, `images` and `expectedLookCount`.** Keep clearing `collections`.
- [ ] **Step 3: The open show may no longer be in the filtered list.** Confirm what `ShowList` does when `selectedCollection` is not among `visibleCollections` — it highlights the selected row by URL comparison. A selected show absent from the list simply has no highlighted row, which is correct and needs no change. Verify rather than assume, and say what you found.
- [ ] **Step 4: The URL still names the show.** The state→URL effect writes `selectedCollection` into the address bar. Confirm a filter change now leaves the show in the URL and adds the filters to the query string, rather than dropping back to `/`. Add a test at the `showUrl.js` level if the decision is expressible there.
- [ ] **Step 5: Build, full suite, `check:css`.**
- [ ] **Step 6: Commit.**

---

### Task 5: `useCollectionImages` — never blank the screen

The largest task in this phase. The image-streaming state moves out of `HighFashionPage` into a hook, and gains keep-previous behaviour.

**Files:**
- Create: `web_ui/src/shared/hooks/useCollectionImages.js`
- Test: `web_ui/src/shared/hooks/useCollectionImages.test.js`
- Modify: `src/features/high-fashion/HighFashionPage.js`

**Interfaces:**
- Produces: `useCollectionImages(collection) -> { images, expectedCount, loading, isStale, error, reload }`
  - `images` — what to render right now. While a new collection is loading and none of its images have arrived, this is still the PREVIOUS collection's images.
  - `isStale` — true while `images` belongs to a collection other than the one requested. The viewer uses it to dim or mark; it must never mean "render nothing".
  - `expectedCount` — from `onMeta`, for ghost slots. `0` until meta arrives.
  - `loading` — a request is in flight.

**The state that moves:** `images`, `currentImageIndex`, `imagesLoading`, `expectedLookCount` are coupled — they change together and are meaningless apart. `currentImageIndex` is the one to think hardest about: it is driven by the URL, the keyboard, the thumb strip and the grid. **Decide deliberately whether it moves into the hook or stays in the page, and justify it in your report.** Moving it means the hook owns navigation; leaving it means the hook must tell the page when to reset it.

**Behaviour, each a test:**
- Selecting a collection when nothing is loaded: `images` is empty, `loading` true.
- Selecting a NEW collection while one is displayed: `images` remains the OLD collection's until the first new image arrives, `isStale` is true, `loading` is true.
- When the first new image arrives: `images` becomes the new collection's, `isStale` false.
- **A failed load does not destroy what is on screen.** The previous collection stays, `error` is set, `isStale` stays true. The user can still look at what they had.
- Selecting collection B then quickly collection C: C wins. B's late-arriving images are discarded, not merged into C's.
- Selecting the collection already displayed is a no-op — no refetch, no flicker.
- `reload()` refetches the current collection.
- Unmounting mid-stream does not set state afterwards.

The existing code already has an `isCurrent()` guard against out-of-order responses (around `HighFashionPage.js:706-720`). Read it and carry its intent — do not reinvent it and do not lose it.

- [ ] **Step 1: Write the failing tests.** Mock `FashionArchiveAPI.streamCollectionImages` — it takes callbacks (`onMeta`, `onImage`, `onDone`), so the mock can drive the hook through a stream step by step, which is exactly what these tests need. Restore the mock in `afterEach`.
- [ ] **Step 2: Run them, confirm they fail.**
- [ ] **Step 3: Implement the hook.**
- [ ] **Step 4: Wire it into `HighFashionPage`** and delete the state it replaces. The lint gate will tell you about anything left unused.
- [ ] **Step 5: Build, full suite, `check:css`.** Smoke renders from phase 1 must still pass — if one fails, a prop contract changed and that is the point of them.
- [ ] **Step 6: Commit.**

---

### Task 6: Show the lookbook growing

**Files:**
- Modify: `src/features/high-fashion/ThumbStrip.js`, `StatusBar.js`, `HighFashionPage.css`
- Test: extend the smoke renders into real assertions for these two

**Interfaces:** consumes `expectedCount` and `isStale` from Task 5, and `lookCounter` from Task 2.

- [ ] **Step 1: Ghost slots in the thumb strip.** When `expectedCount` exceeds `images.length`, render the difference as empty placeholder slots so the strip is full-width from the first image and fills in. Each ghost is inert: not clickable, not focusable, not in the tab order, and carries `aria-hidden`.
- [ ] **Step 2: Ghosts must not shift the real thumbnails.** A ghost occupies exactly the same box as a loaded thumb. If it does not, every image that arrives nudges the strip and the centring effect fights it. Give the ghost the same dimensions as the real thumb by sharing a class, not by duplicating numbers.
- [ ] **Step 3: The status bar counts.** While `images.length < expectedCount`, read `12 / 38 arriving`. When complete, read the plain counter from `lookCounter`. When `expectedCount` is 0 (meta has not arrived), do not render a counter of `n / 0`.
- [ ] **Step 4: Write render tests** asserting: with 12 images and `expectedCount` 38, the strip renders 38 slots of which 26 are ghosts; the ghosts are `aria-hidden`; the status bar says `arriving`; and with `expectedCount` 0 no bogus counter appears.
- [ ] **Step 5: Build, full suite, `check:css`.**
- [ ] **Step 6: Commit.**

---

### Task 7: Session restore, and the filters the URL forgot

**Files:**
- Modify: `src/app/App.js`, `src/features/high-fashion/HighFashionPage.js`
- Create: `web_ui/src/app/session.js` and its test

**Two things, both about the URL not being the whole story.**

**(a) Session restore (#2).** Landing on a bare `/` with a stored last session should reopen it. The URL wins whenever it says anything; storage is only the fallback.

- [ ] **Step 1:** `session.js` is pure: `rememberSession(route)` and `restoreSession()` over `usePersistentState`'s storage, with the same corrupt-value and throwing-storage tolerance. Test it directly.
- [ ] **Step 2:** Store on every real navigation. Restore only when the path is exactly `/` AND there is no query string — a bare root. A URL with filters but no show is a deliberate destination and must not be overridden.
- [ ] **Step 3:** Restore with `replace`, never `push`. A restored session must not put an entry in the history that Back walks into.
- [ ] **Step 4:** A stored session naming a show that no longer resolves must degrade to the archive, exactly as a bad deep link does today. Test it.

**(b) The deferred filter bug.** Carried from phase 1's review: `route.filters` is read only at mount, so same-page Back/Forward across differing filter query strings leaves the address bar and the applied filters disagreeing. The reachable sequence: filters F1 → open show A (pushes `?F1`) → change to F2 (replaces) → open show B (pushes `?F2`) → Back. Show A reopens, but the state→URL effect re-runs on the selection change and overwrites the restored URL with the still-applied F2. **Back silently discards the filters and rewrites that history entry.**

- [ ] **Step 5:** Make the URL→state effect apply `route.filters` when they differ from the applied filters, not only at mount. Guard it so it does not fight the state→URL effect — the same discipline Task 10 of phase 1 established, and `showUrl.js` is where that logic belongs.
- [ ] **Step 6: Write the exact sequence above as a test** at the `showUrl.js` level. It is the one that proves the bug is gone.
- [ ] **Step 7: While here,** collapse the three separate mount-time readings of the URL in `HighFashionPage.js` (`useState(getRoute)`, `useRoute()`, and a direct `window.location` read) into one. They agree today only because they run in the same first render.
- [ ] **Step 8: Build, full suite, `check:css`.**
- [ ] **Step 9: Commit.**

---

## Phase 2 exit criteria

- [ ] `npm run build` clean, with `CI=true` so lint warnings are errors
- [ ] `npm run check:css` exit 0
- [ ] Full suite passes; the count has grown by at least 30
- [ ] `grep -rn "LOOK " web_ui/src --include="*.js"` returns nothing user-facing
- [ ] `grep -rn "localStorage" web_ui/src --include="*.js"` shows access only inside `usePersistentState` and `session.js` — no page reads storage directly
- [ ] Every phase-1 smoke render still passes

**Browser checks — still outstanding, and now cumulative with phase 1's.** These need a signed-in session:
refresh inside a show returns to it; changing a filter leaves the open show alone; a slow collection shows ghost thumbs filling rather than a blank pane; a failed collection leaves the previous one on screen; preferences survive a reload; the status bar reads `n / m arriving`; the sidebar's stored `'closed'` still opens collapsed.
