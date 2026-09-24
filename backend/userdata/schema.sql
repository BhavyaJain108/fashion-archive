-- Per-user data, previously one SQLite file per user under
-- data/user_data/user_NNN/. That layout could not survive hosting: the paths
-- were relative to the working directory, and a container with no persistent
-- disk loses the files on every deploy.
--
-- Columns are flat rather than jsonb because the API queries favourites by
-- season_url, collection_url and look_number — the natural identity of a look.
-- Those are indexable here and would not be inside a jsonb document.

-- A favourite is one of three kinds: a single look, a whole show, or a
-- filtered view of the archive. They share a table because they share a
-- listing — the library shows all three interleaved by date — and because a
-- show is a look with no number rather than a different thing.
CREATE TABLE IF NOT EXISTS favourites (
    id                  bigserial PRIMARY KEY,
    user_id             uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 'look', 'show' or 'view'. Existing rows predate this column and are all
    -- looks, which is what the default gives them.
    kind                text NOT NULL DEFAULT 'look',

    season_name         text NOT NULL,
    season_url          text NOT NULL,
    season_link_text    text,

    collection_designer text NOT NULL,
    collection_url      text NOT NULL,

    -- firstVIEW's own id for the show, which is what the rest of the page
    -- identifies a show by (showId, sameShow, browseCatalog). It is not part
    -- of any uniqueness index yet — switching the key is a separate, deliberate
    -- change — but it is written and kept correct from now on, so that switch
    -- has something to switch to. Null where there is no show (a saved view)
    -- or where collection_url is not a firstVIEW collection page.
    collection_id       text,

    -- Null for a saved show: the show is the whole run, not a position in it.
    look_number         integer,
    look_total          integer,

    -- Where the image lives. Currently a path served by the API; becomes an R2
    -- object key when image storage moves. Same column either way.
    image_path          text NOT NULL,

    -- A saved view is its filters. Null for the other two kinds.
    view_filters        jsonb,
    view_name           text,

    notes               text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_favourites_user
    ON favourites (user_id, created_at DESC);

-- Widening an existing favourites table to the shape above.
--
-- There is no migration versioning here: migrate.py re-runs this file top to
-- bottom on every boot, so everything below has to be a no-op the second time
-- and every time after. ADD COLUMN IF NOT EXISTS and DROP NOT NULL already are;
-- the constraint drop is made so by looking the constraint up rather than
-- naming it.
ALTER TABLE favourites ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'look';
ALTER TABLE favourites ALTER COLUMN look_number DROP NOT NULL;
ALTER TABLE favourites ADD COLUMN IF NOT EXISTS view_filters jsonb;
ALTER TABLE favourites ADD COLUMN IF NOT EXISTS view_name text;
ALTER TABLE favourites ADD COLUMN IF NOT EXISTS collection_id text;

-- The one rule for turning a collection page URL into firstVIEW's id for that
-- show. It lives in the database rather than only in Python because three
-- things need it and they must not be able to disagree: the backfill below,
-- every INSERT (favourites.add calls it by name), and the CHECK constraint
-- that follows. Two spellings of this rule is precisely the class of bug
-- collection_id exists to end.
--
-- `id` wins over `collection` when a URL somehow carries both, which is what
-- firstview.collection_id_from_url does (`qs.get("id") or qs.get("collection")`).
-- A value has to be all digits and has to end where a query parameter ends —
-- `&`, `#`, or the end of the string — so `?id=123abc` is not a show id and
-- `?id=123#top` is. Anything else is null: a URL that is not a collection page,
-- an empty string, or the empty collection_url a saved view carries.
CREATE OR REPLACE FUNCTION favourites_collection_id(collection_url text)
RETURNS text
LANGUAGE sql
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
    SELECT coalesce(
        substring(collection_url from '[?&]id=([0-9]+)(?:[&#]|$)'),
        substring(collection_url from '[?&]collection=([0-9]+)(?:[&#]|$)')
    )
$$;

-- Filling the column in, on rows that already exist and on any row a future
-- change to the rule above would leave stale.
--
-- Re-runs on every boot like everything else here, and the WHERE clause stops
-- matching once it has done its work, so the second run and every run after it
-- updates nothing. Only collection_id is ever written: a row whose
-- collection_url this rule does not recognise keeps its URL exactly as it was
-- and gets a null id, because a null id is the honest statement that we cannot
-- name this show, and a guess would be worse than nothing.
--
-- This is why collection_id is a plain column and not GENERATED ALWAYS AS.
-- A generated column would compute itself, but replacing the function's body
-- later would leave every stored value stale with nothing to repair it; the
-- statement below reapplies the rule to the whole table on the next boot, which
-- is how the rest of this file already repairs rows written by an older writer.
UPDATE favourites
   SET collection_id = favourites_collection_id(collection_url)
 WHERE collection_id IS DISTINCT FROM favourites_collection_id(collection_url);

-- The two must agree, forever, enforced where no caller can route around it.
--
-- The alternative was an assertion in favourites.py, which would only cover
-- writes that go through favourites.py — not psql, not the album migration
-- coming next, not a second service. Here the write and the check share one
-- expression, so the pair cannot become inconsistent by a path we forgot about,
-- and an UPDATE that moves collection_url without moving the id raises instead
-- of quietly producing a second identity for one show.
--
-- Added by name rather than by ADD CONSTRAINT IF NOT EXISTS, which Postgres
-- does not have for CHECK. The UPDATE above ran first, so every existing row
-- already satisfies it and the validation scan cannot fail a boot.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'favourites'::regclass
          AND conname = 'favourites_collection_id_matches_url'
    ) THEN
        ALTER TABLE favourites ADD CONSTRAINT favourites_collection_id_matches_url
            CHECK (collection_id IS NOT DISTINCT FROM favourites_collection_id(collection_url));
    END IF;
END
$$;

-- Identity, one partial index per kind. These are created BEFORE the old
-- constraint is dropped, so there is no instant in which a look has no
-- uniqueness rule covering it and a double-click can land twice.
--
-- A look is season + collection + number; a show is season + collection, which
-- the old four-column constraint could not express because its look_number is
-- null and null is not equal to null. A view is its filters: md5 of the jsonb
-- text, because jsonb renders canonically (keys sorted, whitespace fixed), so
-- the same filters saved twice collide however the client ordered the keys.
-- All three are scoped to the user, so two people can save the same thing.
CREATE UNIQUE INDEX IF NOT EXISTS favourites_look_key ON favourites
    (user_id, season_url, collection_url, look_number) WHERE kind = 'look';
CREATE UNIQUE INDEX IF NOT EXISTS favourites_show_key ON favourites
    (user_id, season_url, collection_url) WHERE kind = 'show';
CREATE UNIQUE INDEX IF NOT EXISTS favourites_view_key ON favourites
    (user_id, md5(view_filters::text)) WHERE kind = 'view';

-- The old UNIQUE (user_id, season_url, collection_url, look_number). Postgres
-- named it, and a generated name is not part of any contract, so it is found by
-- its columns instead of by a name we would be guessing. On a fresh database,
-- and on every boot after the first, the loop finds nothing and does nothing.
DO $$
DECLARE
    old_key text;
BEGIN
    FOR old_key IN
        SELECT con.conname
        FROM pg_constraint con
        WHERE con.conrelid = 'favourites'::regclass
          AND con.contype = 'u'
          AND (
              SELECT array_agg(att.attname ORDER BY att.attname)
              FROM unnest(con.conkey) AS cols(attnum)
              JOIN pg_attribute att
                ON att.attrelid = con.conrelid AND att.attnum = cols.attnum
          ) = ARRAY['collection_url', 'look_number', 'season_url', 'user_id']::name[]
    LOOP
        -- quote_ident rather than a format() call, because this whole file is
        -- handed to psycopg as one string and a percent sign is the one
        -- character it might read as a placeholder.
        EXECUTE 'ALTER TABLE favourites DROP CONSTRAINT ' || quote_ident(old_key);
    END LOOP;
END
$$;

CREATE TABLE IF NOT EXISTS brand_following (
    user_id              uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    brand_id             text NOT NULL,
    brand_name           text NOT NULL,
    followed_at          timestamptz NOT NULL DEFAULT now(),
    notes                text,
    notify_new_products  boolean NOT NULL DEFAULT true,
    notify_price_changes boolean NOT NULL DEFAULT false,

    PRIMARY KEY (user_id, brand_id)
);

-- Shows a user has opened, most recent first.
--
-- Separate from favourites: a favourite is a deliberate keep, this is just
-- where you have been, so you can get back to a show without walking the
-- year/season/gender filters again. Per-user, because it is a history.
--
-- One row per user per show — opening a show again moves it up rather than
-- adding a duplicate, which is what the primary key gives us.
CREATE TABLE IF NOT EXISTS recent_collections (
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    collection_id text NOT NULL,

    designer      text NOT NULL,
    season        text,
    year          integer,
    gender        text,
    collection_url text NOT NULL,

    -- First look, for a thumbnail in the list. Nullable: a show can be
    -- recorded before its images have finished arriving.
    thumbnail_url text,
    look_count    integer,

    viewed_at     timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id, collection_id)
);

CREATE INDEX IF NOT EXISTS idx_recent_collections_user
    ON recent_collections (user_id, viewed_at DESC);

-- Repairing the recents rows already stored.
--
-- A recent is what the favourites drawer keys a save on: a look kept from the
-- drawer is (season_url, collection_url, look_number), and both of the first
-- two come off the row below. Until now this table was written with a bare
-- `?id=NNN` collection_url and with no year at all, while the archive list
-- used `?id=NNN&list=all` and derived a real season_url — so one look kept the
-- two ways landed as two favourites, and removing one left the other.
--
-- The writer is fixed, but every row written before it was is still wrong, and
-- a row is only rewritten when its show is opened again. So both are repaired
-- here. As with everything else in this file this re-runs on every boot: each
-- statement's WHERE clause stops matching once it has done its work, so the
-- second run and every run after it updates nothing.

-- The collection url. This is `firstview.collection_url(collection_id)`,
-- spelled out — the `list=all` is not cosmetic (without it the page returns
-- only the first 20 looks), which is why the list has always used it. Only
-- rows whose id is one of firstVIEW's numeric ones are touched; anything else
-- is not a collection_images.php URL and is left exactly as it was.
UPDATE recent_collections
   SET collection_url = 'https://www.firstview.com/collection_images.php?id='
                        || collection_id || '&list=all'
 WHERE collection_id ~ '^[0-9]+$'
   AND collection_url IS DISTINCT FROM
       'https://www.firstview.com/collection_images.php?id='
       || collection_id || '&list=all';

-- The season a show sits in: gender, year and season, which season_url is a
-- pure function of. The catalogue already knows all three for every show it
-- lists, and `show_index` is the same table the archive list reads them from,
-- so this makes the drawer agree with the list rather than guessing.
--
-- Guarded on the table existing because schema.sql files are applied in order
-- and high_fashion/schema.sql — which creates show_index — is applied after
-- this one. On a first boot the index is not there yet (and, once created, is
-- seeded later still), the guard skips, and the next boot does the work. There
-- are no recents to repair on a first boot anyway.
DO $$
BEGIN
    IF to_regclass('public.show_index') IS NOT NULL THEN
        UPDATE recent_collections r
           SET year   = COALESCE(r.year, s.year),
               gender = COALESCE(r.gender, s.gender),
               season = COALESCE(r.season, s.season)
          FROM show_index s
         WHERE s.collection_id = r.collection_id
           AND ((r.year IS NULL AND s.year IS NOT NULL)
                OR (r.gender IS NULL AND s.gender IS NOT NULL)
                OR (r.season IS NULL AND s.season IS NOT NULL));
    END IF;
END
$$;

-- Albums: named groups of things a user has already saved.
--
-- An album holds favourites, not looks. That is the whole design decision, and
-- everything below follows from it: a tile in an album is a row in favourites,
-- so an album cannot show a picture of something the user has un-saved, and
-- there is no second copy of a look's identity to keep in step with the first.
-- Phase 3 found two separate bugs that were one thing carrying two keys; a
-- membership row that named a look by (season_url, collection_url, number)
-- would have been a third place for that to happen.
CREATE TABLE IF NOT EXISTS albums (
    id          bigserial PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        text NOT NULL CHECK (length(btrim(name)) > 0),

    -- 'grid' now, 'canvas' in phase 6. A CHECK rather than a comment because
    -- layout_mode and sort_by are read straight into a rendering decision and
    -- an ORDER BY respectively; a value neither side knows is a blank page.
    layout_mode text NOT NULL DEFAULT 'grid'  CHECK (layout_mode IN ('grid', 'canvas')),
    sort_by     text NOT NULL DEFAULT 'added' CHECK (sort_by IN ('added', 'designer', 'season')),

    created_at  timestamptz NOT NULL DEFAULT now()
);

-- One name per user, case-insensitively.
--
-- The name is the only handle the user has on an album: the picker that phase 6
-- adds things through lists names, so two albums called "Resort" are two
-- identical rows in that list and a coin flip about which one the thing landed
-- in. Case-insensitive for the same reason `users.email` is citext — "resort"
-- and "Resort" typed a week apart are one album the user meant to reuse, not
-- two they meant to keep apart. Scoped to user_id, so two people naming an
-- album the same thing is fine.
--
-- lower(name) rather than a citext column because this is an ordering and
-- display string everywhere else, and citext would quietly make every
-- comparison in every future query case-insensitive, including ones where that
-- is wrong.
CREATE UNIQUE INDEX IF NOT EXISTS albums_user_name_key ON albums (user_id, lower(name));

-- Which favourites are in which album.
--
-- ON DELETE CASCADE on favourite_id is the point of this table. Un-saving
-- something has to remove it from every album that holds it, in the same
-- statement, without any application code being involved — otherwise a
-- membership row outlives the row it names and the album renders a tile for a
-- favourite that is gone.
--
-- ON DELETE CASCADE on album_id is the cheaper half: deleting an album drops
-- its membership rows and nothing else. The favourites stay saved. An album is
-- an arrangement of things the user kept, not the keeping of them, and the
-- opposite behaviour would turn "delete this album" into silent, unrecoverable
-- deletion of everything in it.
CREATE TABLE IF NOT EXISTS album_items (
    album_id     bigint NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    favourite_id bigint NOT NULL REFERENCES favourites(id) ON DELETE CASCADE,

    -- Sparse, not dense. Items are appended at max + ALBUM_SORT_GAP and a drag
    -- writes the midpoint of its two new neighbours, so reordering N items
    -- costs one UPDATE of one row rather than N. albums.renumber respaces an
    -- album when a gap finally closes, which takes about ten midpoint drops
    -- into the same slot. See backend/userdata/albums.py.
    sort_index   integer NOT NULL DEFAULT 0,

    -- Canvas placement, phase 6. Null in grid mode; a canvas layout is per
    -- album, so these live on the membership row rather than the favourite.
    -- There is no h: a look's height follows from its width and the image's
    -- aspect ratio. z is stacking order.
    x integer, y integer, w integer, z integer,

    -- An album holds a given favourite once. Adding the same thing twice is a
    -- no-op, not a second tile.
    PRIMARY KEY (album_id, favourite_id)
);

-- Reading an album in order.
CREATE INDEX IF NOT EXISTS idx_album_items_order ON album_items (album_id, sort_index);

-- Un-saving a favourite. Postgres indexes the referenced side of a foreign key
-- and not the referencing side, so without this every DELETE from favourites
-- would seq-scan album_items to find the rows to cascade — on the one table
-- that grows with every album every user makes.
CREATE INDEX IF NOT EXISTS idx_album_items_favourite ON album_items (favourite_id);

-- Share links. A token is 22 characters from a CSPRNG and derived from nothing,
-- so a stranger cannot guess one or walk from one to the next. What it points
-- at is a small JSON document: for a look, enough to render it without a
-- session; for a show, the show's id; for an album, the album's id. Resolving
-- a token is read-only and answers only for that one target.
--
-- Revoking sets revoked_at; a revoked token answers 404, not 403, so a revoked
-- link is indistinguishable from one that never existed.
CREATE TABLE IF NOT EXISTS share_tokens (
    token       text PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        text NOT NULL,           -- 'look' | 'show' | 'album'
    target      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    revoked_at  timestamptz
);

CREATE INDEX IF NOT EXISTS idx_share_tokens_user
    ON share_tokens (user_id, created_at DESC);

-- Fixed-window rate limiting, in the database because there is no Redis and
-- the process may be more than one worker. One row per (key, window); the
-- count is bumped atomically by an upsert. Old windows are deleted
-- opportunistically by the same code path.
CREATE TABLE IF NOT EXISTS rate_limits (
    key          text NOT NULL,
    window_start timestamptz NOT NULL,
    count        integer NOT NULL DEFAULT 1,
    PRIMARY KEY (key, window_start)
);

-- The shopping bag: one row per (product, variant) a user has put in it, across
-- every shop. Nothing about money moves here — a line remembers what the product
-- cost when it was added so the bag can say "this changed", and the checkout
-- hands the person to each shop's own cart. No card, no order, no address.
--
-- variant_id and size are nullable because a product read from a page rather
-- than a feed has neither; COALESCE in the unique index keeps such a line from
-- being added twice, since NULLs would otherwise compare unequal.
CREATE TABLE IF NOT EXISTS bag_lines (
    id          bigserial PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    brand       text NOT NULL,           -- the shop's domain, as the roster names it
    itemurl     text NOT NULL,
    handle      text,
    title       text NOT NULL DEFAULT '',
    image       text,
    platform    text,                    -- 'shopify' | 'woo' | NULL
    variant_id  text,
    size        text,
    qty         integer NOT NULL CHECK (qty > 0),
    price       numeric(12, 2),          -- in `currency`, as the catalogue said at add time
    currency    text,
    added_at    timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_bag_lines_variant
    ON bag_lines (user_id, itemurl, COALESCE(variant_id, ''), COALESCE(size, ''));

CREATE INDEX IF NOT EXISTS idx_bag_lines_user
    ON bag_lines (user_id, added_at);
