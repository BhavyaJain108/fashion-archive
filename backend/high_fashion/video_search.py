"""Finding a show's runway video on YouTube.

Replaces scraping Google's video search, which stopped returning anything:
Google now serves a JavaScript shell, so the response contains zero video
links and there is no markup to parse. It was also disallowed by their
robots.txt. This uses YouTube's own Data API instead.

Quota is the whole design constraint
------------------------------------
`search.list` costs 100 units against a default allowance of 10,000 per
day. That is **100 searches a day in total**, shared by every user — which
would not survive three people browsing a 39-year archive.

So a search is only ever made for a (designer, season, gender) nobody has
looked up before:

  * hits are cached permanently — the right video for "Gucci Fall/Winter
    2025" does not change;
  * misses are cached too, because a designer with no runway video would
    otherwise cost 100 units on every click, which is the fastest way to
    exhaust the day;
  * usage is recorded, so the app can say "quota exhausted, try tomorrow"
    instead of surfacing an opaque 403 from Google.

Steady state is therefore zero quota for anything already looked up, and
100 lookups a day for genuinely new shows.

The Claude verifier in `claude_video_verifier.py` still chooses between
candidates. It holds real fashion logic — Couture vs Haute Couture, and
matching 2010 to a 2010-11 show rather than 2009-10 — and it now runs on
clean JSON rather than scraped HTML.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import requests

API_URL = "https://www.googleapis.com/youtube/v3/search"

# What one search.list call costs, per Google's published quota table.
SEARCH_COST_UNITS = 100
DAILY_QUOTA_UNITS = int(os.getenv("YOUTUBE_DAILY_QUOTA", "10000"))

# Enough for the verifier to choose from without changing the cost — the
# call is 100 units whether it returns 1 result or 50.
MAX_RESULTS = 5

TIMEOUT = 15


class QuotaExhausted(RuntimeError):
    """Raised before spending units that are not there."""


@dataclass
class VideoCandidate:
    """One YouTube result, in the shape the Claude verifier expects."""

    title: str
    url: str
    thumbnail_url: str
    video_id: str
    channel: str = ""
    published_at: str = ""


def api_key() -> Optional[str]:
    return os.getenv("YOUTUBE_API_KEY") or os.getenv("YOUTUBE_DATA_API_KEY")


def query_key(designer: str, season: Optional[str], gender: Optional[str]) -> str:
    """Stable cache key for a show.

    Normalised so "Saint Laurent" / "saint  laurent" are one entry rather
    than two lookups costing 100 units each.
    """
    parts = [designer or "", season or "", gender or ""]
    joined = "|".join(p.strip().lower() for p in parts)
    return re.sub(r"\s+", " ", joined)


def build_query(designer: str, season: Optional[str], gender: Optional[str]) -> str:
    """The text actually sent to YouTube."""
    bits = [designer]
    if season:
        bits.append(season)
    if gender and gender.lower() == "men":
        bits.append("menswear")
    bits.append("full fashion show runway")
    return " ".join(b for b in bits if b)


# ---------------------------------------------------------------------------
# Quota accounting
# ---------------------------------------------------------------------------

def units_used_today(conn) -> int:
    row = conn.execute(
        "SELECT units_used FROM youtube_quota WHERE quota_date = %s", (date.today(),)
    ).fetchone()
    return row[0] if row else 0


def remaining_units(conn) -> int:
    return max(0, DAILY_QUOTA_UNITS - units_used_today(conn))


def _spend(conn, units: int) -> None:
    conn.execute(
        """
        INSERT INTO youtube_quota (quota_date, units_used)
        VALUES (%s, %s)
        ON CONFLICT (quota_date)
        DO UPDATE SET units_used = youtube_quota.units_used + EXCLUDED.units_used
        """,
        (date.today(), units),
    )


def quota_status(conn) -> dict[str, Any]:
    used = units_used_today(conn)
    return {
        "used": used,
        "limit": DAILY_QUOTA_UNITS,
        "remaining": max(0, DAILY_QUOTA_UNITS - used),
        "cost_per_search": SEARCH_COST_UNITS,
        "searches_left": max(0, DAILY_QUOTA_UNITS - used) // SEARCH_COST_UNITS,
        "configured": bool(api_key()),
    }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def cached(conn, key: str) -> Optional[dict[str, Any]]:
    """A previous lookup, hit or miss, or None if never searched."""
    row = conn.execute(
        """
        SELECT found, video_id, title, thumbnail_url, youtube_url
          FROM cached_videos WHERE query_key = %s
        """,
        (key,),
    ).fetchone()
    if row is None:
        return None

    found, video_id, title, thumbnail_url, youtube_url = row
    if not found:
        return {"found": False}
    return {
        "found": True,
        "video_id": video_id,
        "title": title,
        "thumbnail": thumbnail_url,
        "youtube_url": youtube_url,
        "embed_url": f"https://www.youtube.com/embed/{video_id}",
    }


def remember(conn, key: str, query_text: str, result: Optional[dict[str, Any]]) -> None:
    """Store a lookup. `result` of None records a miss, which matters as much
    as a hit — it is what stops a videoless designer costing 100 units a
    click."""
    conn.execute(
        """
        INSERT INTO cached_videos (
            query_key, found, video_id, title, thumbnail_url, youtube_url,
            query_text, searched_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (query_key) DO UPDATE SET
            found         = EXCLUDED.found,
            video_id      = EXCLUDED.video_id,
            title         = EXCLUDED.title,
            thumbnail_url = EXCLUDED.thumbnail_url,
            youtube_url   = EXCLUDED.youtube_url,
            query_text    = EXCLUDED.query_text,
            searched_at   = now()
        """,
        (
            key,
            bool(result),
            (result or {}).get("video_id"),
            (result or {}).get("title"),
            (result or {}).get("thumbnail"),
            (result or {}).get("youtube_url"),
            query_text,
        ),
    )


# ---------------------------------------------------------------------------
# The one call that costs quota
# ---------------------------------------------------------------------------

def search(conn, query_text: str) -> list[VideoCandidate]:
    """Ask YouTube for candidates. Spends SEARCH_COST_UNITS.

    Callers must check the cache first; this makes no attempt to.
    """
    key = api_key()
    if not key:
        raise RuntimeError(
            "YOUTUBE_API_KEY is not set. Video lookup needs a YouTube Data "
            "API key; without one the feature stays off rather than falling "
            "back to scraping."
        )

    if remaining_units(conn) < SEARCH_COST_UNITS:
        raise QuotaExhausted(
            f"YouTube quota spent for today "
            f"({units_used_today(conn)}/{DAILY_QUOTA_UNITS} units). "
            f"Cached videos still play; new lookups resume tomorrow."
        )

    params = {
        "part": "snippet",
        "q": query_text,
        "type": "video",
        "videoEmbeddable": "true",   # the player embeds it, so filter early
        "maxResults": MAX_RESULTS,
        "key": key,
    }

    # Count the spend before the response: a call that succeeded at Google
    # and failed in transit still cost units, and under-counting is what
    # produces a surprise 403 mid-session.
    _spend(conn, SEARCH_COST_UNITS)

    resp = requests.get(API_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()

    out: list[VideoCandidate] = []
    for item in resp.json().get("items", []):
        vid = (item.get("id") or {}).get("videoId")
        if not vid:
            continue
        snip = item.get("snippet") or {}
        thumbs = snip.get("thumbnails") or {}
        thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {})
        out.append(VideoCandidate(
            title=snip.get("title", ""),
            url=f"https://www.youtube.com/watch?v={vid}",
            thumbnail_url=thumb.get("url", f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"),
            video_id=vid,
            channel=snip.get("channelTitle", ""),
            published_at=snip.get("publishedAt", ""),
        ))
    return out
