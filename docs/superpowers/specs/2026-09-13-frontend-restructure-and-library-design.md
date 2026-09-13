# Frontend restructure, routing, and the library

Status: approved 2026-09-13, implementation in progress

## Why

Twelve requests arrived at once — back/forward navigation, session restore, a
recents drawer, persisted preferences, a redesigned favourites system, albums,
sharing, honest look naming, and a better loading state. Ten of them land inside
`HighFashionV2.js`, which is 1,662 lines holding roughly thirty `useState`
calls. Built one at a time, that file gets edited six times and the shared
plumbing gets invented six ways.

So the plumbing is built once, and the features land on top of it.

## What this is not

Two things were deliberately left out.

**The collection research bot.** The hard part is not the chatbot, it is
sourcing. Runway reviews that could answer "what was this collection about" are
copyrighted and rate-limited, and a model with no source will invent collection
details — which for an archive is worse than silence. That needs a sourcing
answer before it needs code. Its own spec.

**The My Brands rethink.** Deferred by the user until the full scrape lands and
there are twenty-plus gigabytes of products to design against. Designing that
page now would be designing against the wrong data.

## The scraping question, answered

The concern was that readable URLs would make the site easy to scrape.

They do not. `backend/app.py:188` installs auth deny-by-default:

    install_auth(app, public_endpoints={'health_check'} | PUBLIC_AUTH_ENDPOINTS)

It is a `before_request` hook against an explicit allowlist
(`backend/auth/middleware.py:54`). Every archive, favourites and brand endpoint
requires a session cookie today, and a newly added route is closed unless
somebody names it. A client-side URL is a string the JavaScript reads; it
creates no endpoint. A scraper never reads URLs anyway — it opens the network
tab, sees the API calls, and makes them directly.

Two things genuinely are exposed:

1. **There is no rate limiting anywhere in the backend.** Grepping for
   `limiter|rate_limit|Limiter` returns nothing. Any registered account can pull
   the archive as fast as the server answers.
2. **Sharing punches a public hole by design.** A share link must work without a
   session.

Both are addressed in phase 5, with unguessable tokens and the first rate limit
this codebase has had.

## Architecture

### Directory layout

    src/
      app/
        App.js               shell: auth gate, current route -> page
        router.js            URL <-> state, pushState + popstate
        routes.js            the route table
      features/
        high-fashion/
          HighFashionPage.js composition only
          Filters.js         search box, facets, clear
          ShowList.js        the collections list and its paging
          RecentsDrawer.js   the bottom drawer
          Viewer.js          single and grid modes
          ThumbStrip.js      including ghost slots
          StatusBar.js
          VideoPanel.js
        brands/
          BrandsPage.js
          ProductDetailPanel.js
        library/
          LibraryPage.js     everything saved
          AlbumGrid.js       Finder-style icon view
          AlbumCanvas.js     freeform drag and resize
          SharedView.js      what /s/:token renders
        auth/                moved unchanged
      shared/
        api/
          client.js          BASE_URL, fetch wrapper, 401 handling, SSE
          archive.js  brands.js  saves.js  albums.js  share.js
        hooks/
          usePersistentState.js
          useSaves.js
          useRecents.js
          useCollectionImages.js
          useRoute.js
        lib/
          lookLabel.js
          designerSearch.js
        ui/
          TopBar.js
        styles/
          archive.css

Each feature folder owns its own CSS. `shared/styles/archive.css` owns the
tokens and the `.ar-*` primitives.

### The cascade constraint

`archive.css` must be injected before every feature stylesheet. The `.ar-*`
primitives and the feature classes collide at equal specificity, so whichever
loads last wins. This has already broken once — the sort dropdown on My Brands
expanded to the full toolbar and the search field collapsed to about 26 pixels,
because `import App` preceded `import './styles/archive.css'` and App
transitively pulled in every component stylesheet.

Moving files between folders is exactly how that regression returns. Two
defences:

1. A comment in `index.js` stating the constraint, so the next person to tidy
   the imports knows what they are holding.
2. A verification step that greps the built bundle for the byte offset of
   `.ar-btn` and `.fav-remove` and asserts the first is smaller. That check is
   what caught it last time.

### Routing

No router dependency. One module wrapping `history.pushState` and a `popstate`
listener, and one route table.

| URL | Meaning |
|---|---|
| `/` | High Fashion, nothing open |
| `/hf/:designer/:season` | a show open |
| `/hf/:designer/:season/:n` | a show open at image n |
| `/brands` | My Brands |
| `/brands/:brand/:category?` | a brand, optionally a category |
| `/library` | everything saved |
| `/library/albums/:id` | one album |
| `/s/:token` | a shared target, public |

Filters ride in the query string (`?year=2024&season=fw&city=paris`). A filtered
view is therefore a real URL, which is what makes saving a view possible at all.

Precedence on load: a path other than `/` wins. Bare `/` falls back to the last
session in `localStorage`. Neither present means the default view.

The existing `history.replaceState` scrub in `App.js` stays — a password reset
token must not be left in history. It is narrowed to strip only `token`,
`verified` and `error` rather than the whole query string, because filters now
live there.

### Data model

The existing `favourites` table holds live rows and is extended rather than
replaced.

    ALTER TABLE favourites ADD COLUMN kind text NOT NULL DEFAULT 'look';
    ALTER TABLE favourites ALTER COLUMN look_number DROP NOT NULL;
    ALTER TABLE favourites ADD COLUMN view_filters jsonb;
    ALTER TABLE favourites ADD COLUMN view_name text;

The current constraint is
`UNIQUE (user_id, season_url, collection_url, look_number)`. It cannot express a
saved show, whose `look_number` is null, so it is replaced by three partial
unique indexes — one per kind:

    -- The old constraint's name is Postgres-generated, so the migration looks
    -- it up rather than hardcoding a guess:
    --   SELECT conname FROM pg_constraint
    --    WHERE conrelid = 'favourites'::regclass AND contype = 'u';
    ALTER TABLE favourites DROP CONSTRAINT <that name>;

    CREATE UNIQUE INDEX favourites_look_key ON favourites
        (user_id, season_url, collection_url, look_number) WHERE kind = 'look';

    CREATE UNIQUE INDEX favourites_show_key ON favourites
        (user_id, season_url, collection_url) WHERE kind = 'show';

    CREATE UNIQUE INDEX favourites_view_key ON favourites
        (user_id, md5(view_filters::text)) WHERE kind = 'view';

Existing rows take `kind = 'look'` from the default and keep their identity, so
nothing a user has already saved moves or breaks.

New tables:

    CREATE TABLE albums (
        id          bigserial PRIMARY KEY,
        user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name        text NOT NULL,
        layout_mode text NOT NULL DEFAULT 'grid',   -- 'grid' | 'canvas'
        sort_by     text NOT NULL DEFAULT 'added',  -- 'added'|'designer'|'season'
        created_at  timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE album_items (
        album_id     bigint NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
        favourite_id bigint NOT NULL REFERENCES favourites(id) ON DELETE CASCADE,
        sort_index   integer NOT NULL DEFAULT 0,

        -- Canvas placement. Null in grid mode; a canvas layout is per album, so
        -- these live on the membership row rather than on the favourite.
        x integer, y integer, w integer, z integer,

        PRIMARY KEY (album_id, favourite_id)
    );

    CREATE TABLE share_tokens (
        token      text PRIMARY KEY,
        user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind       text NOT NULL,     -- 'look' | 'show' | 'album'
        target_ref text NOT NULL,     -- collection_url#n, collection_url, album id
        created_at timestamptz NOT NULL DEFAULT now(),
        revoked_at timestamptz
    );

    CREATE INDEX idx_album_items_album ON album_items (album_id, sort_index);
    CREATE INDEX idx_share_tokens_user ON share_tokens (user_id, created_at DESC);

An album holds favourites, not raw looks. Adding something to an album saves it
first if it is not already saved. Removing a favourite cascades out of every
album, which is the behaviour a user expects from a library.

## Features

### Saving — the star

One binary save. Click the star, it fills. Click again, it empties. No
confirmation, no "which album?" prompt. Albums are a later, deliberate act.

The optimistic-with-rollback pattern already exists at
`HighFashionV2.js:738`: the key goes into the set immediately, the request
follows, and a failure puts the set back the way it was. That moves into
`useSaves` and is reused everywhere.

Three things can be saved:

- **A look** — what exists today.
- **A whole show** — new, from the show list row and from the viewer header.
- **A view** — new, from the filter bar. The saved thing is the query string,
  and opening it restores those filters.

Star placement follows Apple Music: a consistent position on the item, outline
until interacted with, filled when saved. Four sites:

1. Single view. Exists (`hf2-fav-btn`, star glyph, `F` key). Kept.
2. Grid tile, top-right. Half exists — `kept` marks saved tiles but is not
   clickable. Becomes a real control.
3. Show list row, trailing edge. New.
4. Filter bar, beside Clear. New.

### The recents drawer

One rectangle pinned to the bottom of the sidebar, reading `RECENTLY SEEN`.
Clicking it expands upward to **20% of the sidebar height**; the show list
shrinks to fit and the drawer scrolls internally. Open or closed is persisted.

`GET /api/recents` already exists and already returns what this needs
(designer, season, thumbnail, look count).

The recents strip on the Favourites page is deleted — the drawer replaces it.
The "Recently opened" block inside the search dropdown
(`HighFashionV2.js:1191`) stays; it costs nothing and serves a different moment.

### Loading a collection

Two changes, both in `useCollectionImages`.

**Never blank the screen.** Selecting a new show keeps the previous show's
images rendered until the first image of the new one arrives, then swaps.
Changing a filter does not clear the open show at all — only choosing a
different show does.

**Show the lookbook growing.** `streamCollectionImages` reports the expected
total through `onMeta`, and `expectedLookCount` already holds it
(`HighFashionV2.js:159`). The thumb strip renders that many slots immediately,
as empty ghosts, and each fills as its image arrives. The status bar reads
`12 / 38 arriving` until the stream completes, then `38`.

No backend change — the data is already on the wire.

### Naming

`shared/lib/lookLabel.js` is the only place that decides what an image is
called.

The word "look" is dropped. `extractLookNumber` (`HighFashionV2.js:254`) parses
the number out of the filename and falls back to the array index, so it is an
image number — detail shots and back views inflate it, and a collection's
"look 34" is frequently not that designer's thirty-fourth look. The single view
shows the number alone; the status bar reads `07 / 38`.

The number itself does not change. It is part of the unique index and the
identity of every saved look; renaming the label is cosmetic, renumbering would
orphan every favourite in the database.

*Open for review: this is a judgement call. If a word reads better than a bare
number, it is a one-line change in `lookLabel.js`.*

### Albums

An album opens as a **Finder-style icon grid** — uniform tiles, a caption under
each, sortable by date added, designer, or season. This is the default and the
mode that ships first.

A **Freeform** toggle switches to a canvas: drag to move, corner handle to
resize, drop to reorder depth. Positions save per album on the `album_items`
row, debounced. Switching back to grid leaves the canvas layout intact.

The canvas is the riskiest item in this spec, which is why it is last and why
the grid does not depend on it.

### Sharing

Sharing mints a random token — 22 characters from a CSPRNG, not derived from the
target, so tokens cannot be guessed or enumerated.

`/s/:token` is added to the public allowlist as a single named endpoint. It
resolves one token to one target and returns exactly that target's data. It
accepts no filters, no pagination beyond the target's own images, and no
parameters other than the token. It cannot be used to walk the archive.

Shareable: a look, a season, an album.

Revocation sets `revoked_at`; a revoked token returns 404, not 403, so a
revoked link is indistinguishable from one that never existed.

**Rate limiting arrives here.** The public share route needs it, and the archive
routes have never had it. A fixed-window counter keyed on IP for public routes
and on user id for authenticated ones, held in Postgres — no new dependency.

## Phases

Each phase ends in a working application.

| Phase | Delivers | Visible |
|---|---|---|
| 1 | Feature folders, `router.js`, api split, shared hooks scaffolded | Back and forward work. Nothing else changes. |
| 2 | Session restore, persisted preferences, load behaviour, naming | No blank screens, ghost thumbs, refresh returns you where you were |
| 3 | Recents drawer, stars everywhere, save-a-view, library page rebuilt | The library becomes real |
| 4 | Albums, grid mode | Named boards |
| 5 | Share tokens, public route, rate limiting | Links you can send |
| 6 | Album canvas | Drag, resize, arrange |

Phase 1 is the only phase with no user-visible payoff, and every later phase
depends on it.

## Risks

**The CSS cascade.** Covered above. The byte-offset assertion runs at the end of
every phase, not only phase 1.

**HighFashionV2's state.** Roughly thirty `useState` calls come apart in phase
1. Some are genuinely coupled — `images`, `currentImageIndex`,
`expectedLookCount` and `viewMode` move together and belong in
`useCollectionImages`. The split is by data, not by component convenience.

**The unique-constraint migration.** Dropping a constraint that live rows depend
on. The three partial indexes must exist before the old constraint is dropped,
in one transaction, and the migration must be verified against a copy of the
real table rather than an empty one.

**The canvas.** Pointer capture, resize handles, z-ordering and debounced
persistence are four separate things that all have to work together. It is last
so that nothing else waits on it.

## Verification

Every phase: `npm run build` clean, the byte-offset cascade assertion, and a
browser check at 1440px and 1100px.

The browser check matters more than usual. The previous conversion of these
pages was verified entirely by build output, grep assertions and code review,
and no one has ever looked at the result in a browser. That gap is closed here.

Phase-specific checks:

- **1** — back and forward across all three pages and into a show; a pasted deep
  URL opens the right show at the right image; a reset-password link still
  strips its token.
- **2** — refresh inside a show returns to it; changing a filter leaves the open
  show alone; a slow collection shows ghost thumbs filling.
- **3** — star a look, a show and a view; all three appear in the library;
  removing one removes the right one. The favourite identity
  `removeFavourite(seasonUrl, collectionUrl, lookNumber)` is positional, and
  reordering those arguments silently deletes the wrong row.
- **4** — an album survives a reload with its sort order.
- **5** — a share link opens signed out; a revoked one 404s; the rate limiter
  returns 429 rather than hanging.
- **6** — a canvas layout survives a reload and a grid round trip.
