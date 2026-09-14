# Phase 4: Albums — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Saved things can be grouped into named albums, and an album opens as a Finder-style icon grid you can sort.

**Architecture:** Two new tables. An album holds favourites, not raw looks — adding something to an album saves it first if it is not already saved, and removing a favourite cascades out of every album. The freeform drag-resize canvas is phase 6; this phase ships the grid, and the grid does not depend on it.

**Tech Stack:** React 18, CRA 5, Jest + `@testing-library/react`, Flask, Postgres 16.

## Global Constraints

- **No new npm dependencies.**
- `react-scripts build` with `CI=true` is the lint gate.
- **Monochrome only** — `--ar-*` tokens from `src/shared/styles/archive.css`. `--ar-danger` is reserved for destructive confirmation.
- **`schema.sql` re-runs on every boot and there is no migration versioning.** Everything you add must be idempotent, forever. This was verified in a real container in phase 3 and must stay true.
- **A favourite's identity is positional and URL-based**, and phase 3 found two separate bugs where one thing got two keys. Treat every new path that creates a favourite as a candidate for the same bug.
- Commit after every task. Never `--no-verify`. Branch `master`, commit locally, do not push.
- Run npm commands from `web_ui/`.
- The Write/Edit tools wrongly believe the session is in a deleted git worktree. Use Bash for file changes.
- `postgres:16-alpine` is pulled. Use throwaway containers with distinct names and no published ports; remove them with their volumes. **Never touch `insurance-processor-postgres` and never use port 5432.** Disk is tight — pull nothing new.

## Starting state

444 JS tests in 26 suites; 753 Python. Verified:

- `favourites` has `kind` (`'look'|'show'|'view'`), a nullable `look_number`, `view_filters jsonb`, `view_name`, and three partial unique indexes.
- `src/shared/hooks/useSaves.js` — one store, one key function per kind, exact-match `Set` lookup, per-key write serialisation, rollback against the current list.
- `src/features/library/LibraryPage.js` — renders all three kinds; imports `navigate` from `app/router` directly rather than taking a prop.
- `favourites.list_all` has a cap but the library is still fetched whole on every archive-page mount.

---

### Task 1: `collection_id`, before albums make it permanent

The phase-3 review's strongest recommendation, and it comes first because album membership rows will reference favourites by id and bake in whatever identity they have.

Favourites key on `(season_url, collection_url, look_number)` — two URL strings. The rest of the page has moved to `collection_id` (`showId`, `sameShow`, `browseCatalog({collectionId})`). **Both bugs phase 3 found were URL-spelling differences that a `collection_id` would not have had.**

**Files:** `backend/userdata/schema.sql`, `backend/userdata/favourites.py`, `backend/api/favorites_routes.py`, `web_ui/src/shared/hooks/useSaves.js`, `web_ui/src/shared/api/saves.js`

- [ ] **Step 1: Add `collection_id text` to `favourites`,** idempotently, and store it on every write. It is derivable from `collection_url` (`fv.collection_id_from_url`), so backfill existing rows in `schema.sql` the way phase 3 backfilled `collection_url`.
- [ ] **Step 2: Do NOT change the unique indexes in this task.** Adding a column and populating it is reversible; re-keying the table is not, and it would need a merge strategy for the duplicate rows phase 3 left behind. This task makes the better key available; deciding to switch to it is a separate, deliberate change.
- [ ] **Step 3: Assert the two agree.** Add a check that `collection_id` always matches what `collection_url` parses to, so the moment a path writes an inconsistent pair a test fails rather than a user getting two rows.
- [ ] **Step 4: Verify against a real Postgres,** including the backfill on rows that already exist and the second- and third-run no-op.
- [ ] **Step 5: Commit.**

---

### Task 2: The album tables

**Files:** `backend/userdata/schema.sql`, create `backend/userdata/albums.py`, tests

```sql
CREATE TABLE IF NOT EXISTS albums (
    id          bigserial PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        text NOT NULL,
    layout_mode text NOT NULL DEFAULT 'grid',   -- 'grid' | 'canvas'
    sort_by     text NOT NULL DEFAULT 'added',  -- 'added'|'designer'|'season'
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS album_items (
    album_id     bigint NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    favourite_id bigint NOT NULL REFERENCES favourites(id) ON DELETE CASCADE,
    sort_index   integer NOT NULL DEFAULT 0,
    -- Canvas placement, phase 6. Null in grid mode; a canvas layout is per
    -- album, so these live on the membership row rather than the favourite.
    x integer, y integer, w integer, z integer,
    PRIMARY KEY (album_id, favourite_id)
);
```

- [ ] **Step 1: `ON DELETE CASCADE` on `favourite_id` is the point.** Removing a favourite must drop it out of every album. Prove it with a real database, not by reading the DDL.
- [ ] **Step 2: An album name is per user, not global.** Decide whether two albums of the same name are allowed for one user and enforce whatever you decide. Say which and why.
- [ ] **Step 3: `sort_index` needs a story.** Reordering N items must not need N updates on every drag. Decide the approach (gaps, fractional, or full rewrite on reorder) and say why — phase 6 will drag these.
- [ ] **Step 4: A favourite can be in many albums; an album holds a favourite once.** The primary key gives you the second. Test both.
- [ ] **Step 5: Verify idempotency and the cascade against a real Postgres.**
- [ ] **Step 6: Commit.**

---

### Task 3: The album endpoints

**Files:** `backend/api/` (a new routes module or an extension of the favourites one — decide and justify), `web_ui/src/shared/api/albums.js`, tests

- [ ] **Step 1: Create, rename, delete an album; list a user's albums with a count and a cover thumbnail.**
- [ ] **Step 2: Add to and remove from an album.** **Adding something not yet saved must save it first** — that is the spec's rule, and it means the add endpoint takes a target the way the favourites endpoint does, not just an id. Do it in one transaction so a failed save cannot leave a membership row pointing at nothing.
- [ ] **Step 3: Reorder.** One request for a reorder, not one per item.
- [ ] **Step 4: Everything is scoped to `current_user()`.** An album id from another user is a 404, not a 403 — do not confirm the existence of other people's rows. Test it with two users.
- [ ] **Step 5: Register the routes** the way the others are registered, and check they land behind the auth allowlist (`backend/app.py` is deny-by-default; a new route is closed unless named, which is what you want).
- [ ] **Step 6: Test against a real Postgres** through Flask's test client, the way `tests/db/test_favourites_routes.py` does.
- [ ] **Step 7: Commit.**

---

### Task 4: `useAlbums`

**Files:** `web_ui/src/shared/hooks/useAlbums.js`, tests

- [ ] **Step 1: Match the house style** — read `useSaves.js` first. It has per-key write serialisation, optimistic update, and rollback against the current list rather than a snapshot. Those decisions were each the result of a review round.
- [ ] **Step 2: Adding to an album is two server effects** (save, then add) behind one user action. The optimistic update must reflect both, and rollback must undo both.
- [ ] **Step 3: Honour `success: false`.** Phase 3 found `useSaves` silently swallowing a refused delete. Do not repeat it.
- [ ] **Step 4: Test rollback for every operation**, not just the happy path.
- [ ] **Step 5: Commit.**

---

### Task 5: The album grid

**Files:** `web_ui/src/features/library/AlbumGrid.js` + CSS, `LibraryPage.js`, `src/app/routes.js` if needed

**In the user's words:** "see it in a sorted order — similar to files on a file explorer on Mac icons."

- [ ] **Step 1: Uniform tiles, a caption under each, in a grid.** Finder's icon view is the reference: even spacing, labels under the icon, selection on click.
- [ ] **Step 2: Sortable** by date added, designer, and season. The control persists per album (`sort_by` on the table).
- [ ] **Step 3: `/library/albums/:id` already exists in the route table** and currently renders the library. Make it render the album. Back from an album returns to the library.
- [ ] **Step 4: Tiles must not reflow as thumbnails load.** Same discipline as the ghost slots and the star: reserve the box, and **measure it in headless Chrome** rather than trusting it.
- [ ] **Step 5: An album holds three kinds.** A saved show and a saved view in a grid of looks need a representation — decide it and say why. A view has no image at all.
- [ ] **Step 6: Empty album state.**
- [ ] **Step 7: Commit.**

---

### Task 6: Putting things in albums

**Files:** `LibraryPage.js`, `src/shared/ui/`, `Viewer.js` / `ShowList.js` if you add an entry point there

- [ ] **Step 1: From the library**, select one or more saved things and add them to an album, including a new one.
- [ ] **Step 2: The star stays a star.** The spec is explicit: one click saves, and albums are a later deliberate act. Adding to an album must not become a second thing the star does, and starring must never prompt "which album?".
- [ ] **Step 3: Removing from an album is not unsaving.** Two different destructive acts, and the user must be able to tell which one they are doing. Only one of them deserves `--ar-danger`.
- [ ] **Step 4: Test that removing a favourite removes it from its albums** — the cascade, from the UI's point of view.
- [ ] **Step 5: Commit.**

---

### Task 7: The two deferred items

Small, and phase 5 and 6 both build on this page.

- [ ] **Step 1: `LibraryPage` takes `navigate` as a prop** rather than importing it from `app/router`. It is untestable without stubbing the router module otherwise, and it breaks the navigation-purity phase 1 established.
- [ ] **Step 2: Paginate the library fetch.** It is fetched whole on every archive-page mount. A Finder grid over an unbounded fetch is the sidebar-at-21.6-seconds problem again (commit `69207815`).
- [ ] **Step 3: Commit.**

---

## Phase 4 exit criteria

- [ ] `CI=true npm run build` clean; `npm run check:css` exit 0
- [ ] Full suite passes; count grown by at least 40 from 444
- [ ] `schema.sql` applied three times against a seeded database is a no-op after the first — verified in a real container
- [ ] Deleting a favourite removes it from every album — verified against a real database
- [ ] An album id belonging to another user returns 404 — verified with two users
- [ ] No new colour outside the token block
- [ ] Album tiles measured, not eyeballed, for reflow

**Browser checks — outstanding and cumulative with phases 1-3.** Needs a signed-in session: creating an album, adding to it, the grid at 1440px and 1100px, sorting, and removing from an album versus unsaving.
