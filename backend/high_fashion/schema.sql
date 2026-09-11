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
