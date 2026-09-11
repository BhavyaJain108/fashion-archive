-- Per-user data, previously one SQLite file per user under
-- data/user_data/user_NNN/. That layout could not survive hosting: the paths
-- were relative to the working directory, and a container with no persistent
-- disk loses the files on every deploy.
--
-- Columns are flat rather than jsonb because the API queries favourites by
-- season_url, collection_url and look_number — the natural identity of a look.
-- Those are indexable here and would not be inside a jsonb document.

CREATE TABLE IF NOT EXISTS favourites (
    id                  bigserial PRIMARY KEY,
    user_id             uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    season_name         text NOT NULL,
    season_url          text NOT NULL,
    season_link_text    text,

    collection_designer text NOT NULL,
    collection_url      text NOT NULL,

    look_number         integer NOT NULL,
    look_total          integer,

    -- Where the image lives. Currently a path served by the API; becomes an R2
    -- object key when image storage moves. Same column either way.
    image_path          text NOT NULL,

    notes               text,
    created_at          timestamptz NOT NULL DEFAULT now(),

    -- A look is identified by season + collection + number. Scoped to the user
    -- so two people can favourite the same look.
    UNIQUE (user_id, season_url, collection_url, look_number)
);

CREATE INDEX IF NOT EXISTS idx_favourites_user
    ON favourites (user_id, created_at DESC);

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
