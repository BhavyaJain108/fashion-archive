# Phase 3: Saving, and the library — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The star becomes the one way to keep anything — a look, a whole show, or a filtered view. Recently-seen shows move onto the archive page as a drawer under the show list. The Favourites page becomes a library of all three.

**Architecture:** The `favourites` table gains a `kind` column and loses the unique constraint that assumed every row is a look. One `useSaves` hook generalises the existing `useFavourites`. The star is one component used in four places.

**Tech Stack:** React 18, CRA 5, Jest + `@testing-library/react`, Flask, Postgres.

## Global Constraints

- **No new npm dependencies.** `@testing-library/react` is available.
- **`react-scripts build` with `CI=true` is the lint gate.**
- **Monochrome.** Black, white, grey via the `--ar-*` tokens in `src/shared/styles/archive.css`. `--ar-danger` (#cc0000) is reserved for destructive confirmation and nothing else.
- **`removeFavourite(seasonUrl, collectionUrl, lookNumber)` is positional and two arguments are URLs.** A mismatched triple deletes a different row from the user's account, silently, and fails no test. Every call must take all three off one object in one expression.
- **The schema is applied by re-running `schema.sql` on every boot** (`backend/auth/migrate.py`). There is no migration versioning and no down-migration. Everything you add to `schema.sql` must therefore be idempotent — safe to run against a fresh database and against one that already has the change.
- Commit after every task. Never `--no-verify`. Branch `master`, commit locally, do not push.
- Run npm commands from `web_ui/`.
- The Write/Edit tools wrongly believe the session is in a deleted git worktree. Use Bash for file changes.

## Starting state

297 tests in 18 suites. Verified facts:

- `backend/userdata/schema.sql` — `favourites` has `UNIQUE (user_id, season_url, collection_url, look_number)` and `look_number integer NOT NULL`. `recent_collections` exists and is populated.
- `backend/userdata/favourites.py` exposes `add`, `remove`, `exists`, `list_all`, `stats`. `recents.py` exposes `record`, `list_recent`, `clear`.
- `backend/api/favorites_routes.py` — 5 endpoints, all scoped to `current_user()`.
- `GET /api/recents` already returns designer, season, thumbnail and look count.
- `src/features/high-fashion/useFavourites.js` — the star's logic, keyed off the on-screen collection, with optimistic-update-and-rollback.
- `src/features/high-fashion/ShowList.js` — rows are `.hf2-collection-item`, with a `.num` and a `.body`. No star.
- `src/features/library/LibraryPage.js` — a `.fav-recents` strip, a sidebar, a GRID/SINGLE toggle, a thumb strip. It renders looks only.
- `onOpenRecent` is a prop `LibraryPage` accepts and `App.js` has never passed. It is inert on master too.

Read the files before editing — line numbers drift.

---

### Task 1: The schema, idempotently

**Files:** `backend/userdata/schema.sql`, `backend/userdata/favourites.py`, and its tests

**The change:**

```sql
ALTER TABLE favourites ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'look';
ALTER TABLE favourites ALTER COLUMN look_number DROP NOT NULL;
ALTER TABLE favourites ADD COLUMN IF NOT EXISTS view_filters jsonb;
ALTER TABLE favourites ADD COLUMN IF NOT EXISTS view_name text;
```

The old constraint cannot express a saved show, whose `look_number` is null. It is replaced by three partial unique indexes:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS favourites_look_key ON favourites
    (user_id, season_url, collection_url, look_number) WHERE kind = 'look';
CREATE UNIQUE INDEX IF NOT EXISTS favourites_show_key ON favourites
    (user_id, season_url, collection_url) WHERE kind = 'show';
CREATE UNIQUE INDEX IF NOT EXISTS favourites_view_key ON favourites
    (user_id, md5(view_filters::text)) WHERE kind = 'view';
```

- [ ] **Step 1: Drop the old constraint by lookup, not by guessed name.** Postgres generated it, so the name is not guaranteed. Use a `DO $$ ... $$` block that finds the unique constraint on `favourites` covering those four columns and drops it, and that does nothing when it is already gone. Write it so running `schema.sql` twice is a no-op the second time — that is not optional here, it runs on every boot.
- [ ] **Step 2: Order matters.** The three partial indexes must exist before the old constraint is dropped, so there is no window in which duplicate looks can be inserted. Put them first.
- [ ] **Step 3: Existing rows.** They take `kind = 'look'` from the column default and keep their identity. Nothing a user has saved moves. State in your report how you confirmed that, given you cannot run this against the real table.
- [ ] **Step 4: Teach `favourites.py` about `kind`.** `add` takes a kind and the fields that kind needs; `remove` and `exists` match on the right key for the kind; `list_all` returns all kinds with enough shape for the UI to tell them apart. Keep the existing signatures working for looks — the frontend still calls them that way until Task 3.
- [ ] **Step 5: Test what you can.** There is no live database in this environment and `psycopg` is not installed, so you cannot execute the SQL. Do what is honestly possible: unit-test the Python that builds the queries, and parse the SQL to assert the ordering and idempotency properties. **Do not claim the migration is verified.** Say plainly in your report that it has never been run.
- [ ] **Step 6: Commit.**

---

### Task 2: The endpoints for a show and a view

**Files:** `backend/api/favorites_routes.py`, `web_ui/src/shared/api/saves.js`, tests

**Interfaces:**
- `POST /api/favourites` accepts a `kind` of `'look'`, `'show'` or `'view'` with the fields that kind needs.
- `DELETE` matches on the right key for the kind.
- `GET /api/favourites` returns all three, each tagged.

- [ ] **Step 1: Keep the look shape exactly as it is.** The frontend calls it positionally today and Task 3 changes that; a break here is a break in production before the frontend catches up.
- [ ] **Step 2: A saved view is its filters.** Store the filter object. The unique index is on `md5(view_filters::text)`, so the same filter set saved twice must collide — which means the JSON the server stores must be canonical, not whatever key order the client sent. Normalise it server-side. Test that `{year, city}` and `{city, year}` produce one row, not two.
- [ ] **Step 3: A view needs a name** for the library to list it. Derive one from the filters when the client does not supply one.
- [ ] **Step 4: Validate `kind`.** An unknown kind is a 400, not a row with a junk kind that no index covers.
- [ ] **Step 5: Extend `shared/api/saves.js`** with the new calls. Keep `removeFavourite`'s existing positional signature — phase 3 does not get to change it while four new call sites are being added.
- [ ] **Step 6: Test the routes** the way the existing backend tests work — look at `tests/unit/` for the pattern before inventing one.
- [ ] **Step 7: Commit.**

---

### Task 3: `useSaves`

**Files:** Create `web_ui/src/shared/hooks/useSaves.js` and its test. Modify `src/features/high-fashion/useFavourites.js` (or replace it).

**Interfaces:**
- `useSaves()` returns `{ isSaved(target), toggle(target), saves, loading, error }` where a `target` is `{ kind: 'look'|'show'|'view', ... }`.

- [ ] **Step 1: Carry forward what `useFavourites` already gets right** — the optimistic update with rollback on failure, and keying off the on-screen collection rather than the requested one. Read it and its tests first; both were the subject of review rounds and the reasons are in the comments.
- [ ] **Step 2: One key function per kind.** A look is season+collection+number; a show is season+collection; a view is its canonical filters. Pure, and tested directly.
- [ ] **Step 3: Saving a show and saving one of its looks are independent.** Starring a whole show must not appear to star every look in it, and un-starring a look must not un-star the show. Test both directions.
- [ ] **Step 4: Rollback must restore the exact previous state** for all three kinds, not just looks.
- [ ] **Step 5: Commit.**

---

### Task 4: The star, in four places

**Files:** Create `web_ui/src/shared/ui/SaveStar.js` + CSS. Modify `Viewer.js`, `ShowList.js`, `Filters.js`.

**The affordance, in the user's words:** "like stars on Apple Music — both in terms of placement and how to click on them." That means: a consistent position on the item, outline until saved, filled when saved, single click toggles, no confirmation, no menu.

- [ ] **Step 1: One component.** `SaveStar` takes `saved`, `onToggle`, a label for assistive technology, and a size. It is a `<button>`, not a `<div>` — it is keyboard-reachable and announces its state with `aria-pressed`.
- [ ] **Step 2: Single view.** Already exists as `hf2-fav-btn`. Replace it with `SaveStar` and confirm the `F` key still works.
- [ ] **Step 3: Grid tile.** A saved tile currently gets a `kept` class and nothing clickable. Add a real star, top-right. **Clicking the star must not also select the tile** — stop the event.
- [ ] **Step 4: Show list row.** New. Saves the whole show. Same rule: clicking the star must not open the show.
- [ ] **Step 5: Filter bar.** New. Saves the current view. It is disabled when no filter is set — saving "everything" is not a view.
- [ ] **Step 6: The row must not reflow when a star appears.** Reserve its space so a list of shows does not jitter as saves load. Verify the way phase 2 verified the ghost slot, by measuring, not by eye.
- [ ] **Step 7: Test each of the four** — that clicking it calls toggle with the right target shape, and that clicking it does not trigger the row's own click.
- [ ] **Step 8: Commit.**

---

### Task 5: The recents drawer

**Files:** Create `src/features/high-fashion/RecentsDrawer.js`. Modify `HighFashionPage.js`, its CSS. Create `src/shared/hooks/useRecents.js`.

**In the user's words:** "recent shows should instead just be on the high fashion page — and be easily accessible through like a list that expands right below the show list. So it will be one rectangle on the bottom called recently seen — and open upwards shortening the show list — visible length 20% of the space and you can scroll and see other recently viewed ones."

- [ ] **Step 1: `useRecents`** over the existing `GET /api/recents`. Same tolerances as the other hooks.
- [ ] **Step 2: Collapsed, it is one rectangle** at the bottom of the sidebar reading `RECENTLY SEEN`.
- [ ] **Step 3: Expanded, it takes 20% of the sidebar height** and the show list shrinks to fit. The drawer scrolls internally; the sidebar as a whole does not grow.
- [ ] **Step 4: Open or closed is persisted** with `usePersistentState`.
- [ ] **Step 5: Clicking a recent opens that show** — the same path as clicking a row in the show list, so the URL and the keep-previous loading behaviour both apply.
- [ ] **Step 6: Delete the recents strip from the library page.** That is the "instead" in the request. Its CSS goes too.
- [ ] **Step 7: Leave the "Recently opened" block in the search dropdown alone.** It serves a different moment and costs nothing.
- [ ] **Step 8: Test** that expanding shrinks the list rather than overflowing the sidebar, and that the drawer scrolls rather than growing. Measure it.
- [ ] **Step 9: Commit.**

---

### Task 6: The library page holds all three kinds

**Files:** `src/features/library/LibraryPage.js` and its CSS

- [ ] **Step 1: The sidebar groups by kind** — looks, shows, views — as well as the grouping it already has.
- [ ] **Step 2: A saved show renders as a show**, not as a look with missing fields. Clicking it opens it on the archive page.
- [ ] **Step 3: A saved view renders as its filters** and its name. Clicking it opens the archive page with those filters applied — which is a URL, so it is `buildRoute` plus `navigate`, not new state.
- [ ] **Step 4: Removing anything removes the right thing.** The positional-argument hazard applies to every kind now. Test each.
- [ ] **Step 5: Empty states per kind** — a user with looks but no views should be told what a view is, not shown a blank pane.
- [ ] **Step 6: The nav label becomes "Library"** and the page key changes from `'favourites'`. Phase 1 deliberately deferred this until the page earned the name. Update `TopBar.js`, `App.js`'s `pageKeyForRoute`, and the route table if it names it. `routes.js` already uses `/library`.
- [ ] **Step 7: Commit.**

---

### Task 7: Saving a view, end to end

**Files:** `src/features/high-fashion/Filters.js`, `HighFashionPage.js`, `src/features/library/LibraryPage.js`

**In the user's words:** "saving any view is favouriting it."

- [ ] **Step 1: The star in the filter bar saves the current filter set** — which is already in the URL's query string, so the thing being saved is a URL, not a new concept.
- [ ] **Step 2: The same filters saved twice is one row.** The server enforces it; the UI must show the star already filled when the current filters match a saved view.
- [ ] **Step 3: Opening a saved view restores those filters exactly**, including gender, which has the awkward default. Test the round trip: save a view, change the filters, open the saved view, assert the filters match what was saved.
- [ ] **Step 4: A saved view does not carry the open show.** It is a list state, not a reading position.
- [ ] **Step 5: Commit.**

---

## Phase 3 exit criteria

- [ ] `CI=true npm run build` clean; `npm run check:css` exit 0
- [ ] Full suite passes; count grown by at least 40 from 297
- [ ] Every `removeFavourite` call site takes all three arguments off one object in one expression — grep and confirm by eye
- [ ] `schema.sql` applied twice in a row is a no-op the second time (asserted by parsing, since it cannot be run here)
- [ ] The nav says "Library"
- [ ] No new colour: `grep -rn "#[0-9a-fA-F]\{3,6\}" web_ui/src --include="*.css"` introduces nothing outside the token block

**Browser checks — outstanding and cumulative with phases 1 and 2.** Needs a signed-in session: star a look, a show and a view and see all three in the library; remove one and confirm the right one goes; the recents drawer opening upward to 20% and scrolling; the star not firing the row's click; a saved view reopening with its filters.
