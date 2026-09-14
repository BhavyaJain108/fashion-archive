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
