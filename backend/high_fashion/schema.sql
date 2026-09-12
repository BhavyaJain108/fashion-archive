-- Shows already fetched from firstVIEW and stored in R2.
--
-- Without this, opening a show re-downloads every look from firstVIEW even if
-- it was fetched a minute ago: a 250-look show is 250 requests to someone
-- else's site and the better part of a minute before anything appears. The
-- images are already in R2 after the first fetch; this table is what lets us
-- know that and hand back the URLs directly.
--
-- Shared, not per-user. The pixels are identical whoever asks for them, so a
-- show one person opened is instant for the next.
--
-- Bounded by last_accessed_at: the least recently opened shows are evicted,
-- with their R2 objects, once the table exceeds its limit. Deliberately small,
-- because this is a personal archive for a handful of people, not a CDN.

CREATE TABLE IF NOT EXISTS cached_collections (
    collection_id    text PRIMARY KEY,

    designer         text,
    season           text,
    gender           text,
    category         text,
    shoot_type       text,

    -- Ordered [{index, filename, key, url}], one entry per look. `key` is the
    -- R2 object key, kept so eviction can delete the objects as well as the
    -- row; `url` is what the browser loads.
    images           jsonb NOT NULL,
    look_count       integer NOT NULL,

    -- Which size was stored, so a request for a different one is a miss
    -- rather than silently the wrong pixels.
    quality          text NOT NULL,

    cached_at        timestamptz NOT NULL DEFAULT now(),
    last_accessed_at timestamptz NOT NULL DEFAULT now()
);

-- Eviction reads this in ascending order; the ordering is the whole point.
CREATE INDEX IF NOT EXISTS idx_cached_collections_lru
    ON cached_collections (last_accessed_at);

-- Video lookups, so the YouTube quota is spent once per show and never again.
--
-- search.list costs 100 units against a 10,000/day allowance: 100 searches a
-- day, total, across every user. That is nothing for a 39-year archive browsed
-- by several people — but a lookup is perfectly cacheable, because "Gucci
-- Fall/Winter 2025" resolves to the same video for everyone, permanently.
--
-- Misses are cached too. A designer with no runway video on YouTube would
-- otherwise burn 100 units every time someone clicked the button, which is the
-- fastest possible way to exhaust the day's quota.
CREATE TABLE IF NOT EXISTS cached_videos (
    query_key     text PRIMARY KEY,   -- normalised designer + season + gender

    -- Null when the search ran and found nothing worth showing. `found`
    -- distinguishes that from "never looked", which is simply no row.
    found         boolean NOT NULL,
    video_id      text,
    title         text,
    thumbnail_url text,
    youtube_url   text,

    -- What was actually asked, kept for debugging a bad match.
    query_text    text NOT NULL,
    searched_at   timestamptz NOT NULL DEFAULT now()
);

-- Units spent per day, so the app can say "quota exhausted" rather than
-- returning an opaque 403 from Google, and so usage is visible before it runs
-- out. Google resets at midnight Pacific; the date here is that day.
CREATE TABLE IF NOT EXISTS youtube_quota (
    quota_date date PRIMARY KEY,
    units_used integer NOT NULL DEFAULT 0
);

-- Every show firstVIEW lists, held locally so browsing does not crawl them.
--
-- Navigating used to mean a live crawl of their results pages: each filter
-- change was 1-3 seconds and a handful of requests to someone else's site,
-- for a listing that only changes when a season is added. 55,700 rows is
-- small enough to keep and query directly, which makes the archive list
-- instant, makes the filter options exact instead of guessed, and makes
-- free-text search over shows possible at all -- firstVIEW's own search
-- covers designer names and nothing else.
--
-- Shared and derived, not user data: it can be rebuilt from the site at any
-- time, and is seeded from the committed shows.json.gz at boot.
CREATE TABLE IF NOT EXISTS show_index (
    collection_id text PRIMARY KEY,

    designer      text,
    season        text,
    year          integer,
    gender        text,
    category      text,
    shoot_type    text,
    city          text,

    -- Everything above, lowercased and unaccented, plus the abbreviations
    -- people actually type: "fw25", "aw2025", "rtw", "couture". This is what
    -- lets "chanel fw25" be one query rather than a parse into three filters.
    search_text   text NOT NULL,

    -- Display order. firstVIEW lists newest first, and within a year the
    -- later season first; this reproduces that without storing crawl
    -- positions, so the list reads the way the site's does.
    sort_rank     integer NOT NULL DEFAULT 0
);

-- The archive list filters on these constantly.
CREATE INDEX IF NOT EXISTS idx_show_index_browse
    ON show_index (gender, year, sort_rank);
CREATE INDEX IF NOT EXISTS idx_show_index_designer
    ON show_index (lower(designer));
-- 55,700 rows is small enough that a scan for a substring is a few
-- milliseconds, so search needs no extension and no tsvector to maintain.
CREATE INDEX IF NOT EXISTS idx_show_index_sort
    ON show_index (sort_rank);
