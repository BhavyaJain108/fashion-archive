"""The local copy of firstVIEW's listing, and the queries over it.

Browsing used to crawl their results pages live: every filter change cost
1-3 seconds and a handful of requests to someone else's site, for a listing
that changes only when a season is added. 55,700 shows is 7.8 MB, which is
nothing to keep and everything to be able to query.

Three things follow from holding it:

  * the archive list is a database query, not a crawl, so it is instant and
    firstVIEW is only asked for images;
  * filter options are exact — the coverage catalog could only say "at
    least 20", because that is one results page;
  * free-text search over shows exists at all. firstVIEW can search
    designer names and nothing else, so "chanel fw25" had no query to be.

Rebuilt with firstview.build_show_index (2,785 requests, ~8 minutes) and
committed; firstview.refresh_show_index tops it up for a couple of dozen.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

# Within a year, later seasons first — the order firstVIEW itself lists in,
# and the order a season is spoken about ("Fall 2026" is the new one).
SEASON_RANK = {
    "Fall / Winter": 4,
    "Prefall": 3,
    "Spring / Summer": 2,
    "Cruise": 1,
}

# What people type, against what the site calls it. The index carries both,
# so a query never has to be parsed into filters to be understood.
SEASON_ALIASES = {
    "Fall / Winter": ["fall winter", "fw", "aw", "autumn winter", "fall"],
    "Spring / Summer": ["spring summer", "ss", "spring"],
    "Cruise": ["cruise", "resort"],
    "Prefall": ["prefall", "pre fall", "pf"],
}

CATEGORY_ALIASES = {
    "Ready-to-Wear": ["ready to wear", "rtw"],
    "Haute Couture": ["haute couture", "couture"],
    "Swim": ["swim", "swimwear"],
}


def normalise(value: str) -> str:
    """Lowercase, unaccented, punctuation flattened to single spaces."""
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def search_text(record: dict) -> str:
    """Everything about one show that someone might type.

    Includes the shorthand: "fw25" and "aw2025" for a Fall / Winter 2025
    show, "rtw" for Ready-to-Wear. Without these the abbreviations everyone
    actually uses would need parsing out of the query instead, which is
    guesswork about word order that fails silently.
    """
    year = record.get("y")
    parts = [
        normalise(record.get("d") or ""),
        normalise(record.get("g") or ""),
        normalise(record.get("p") or ""),
        normalise(record.get("t") or ""),
        str(year) if year else "",
    ]

    season = record.get("s")
    if season:
        parts.extend(SEASON_ALIASES.get(season, [normalise(season)]))
        if year:
            short = f"{year % 100:02d}"
            for alias in SEASON_ALIASES.get(season, []):
                if " " in alias:
                    continue
                # "fw2025" and "fw25", the two ways it is ever written.
                parts.append(f"{alias}{year}")
                parts.append(f"{alias}{short}")

    category = record.get("n")
    if category:
        parts.extend(CATEGORY_ALIASES.get(category, [normalise(category)]))

    return " ".join(p for p in parts if p)


def sort_rank(record: dict) -> int:
    """Newest first. Year dominates; season orders within it."""
    year = record.get("y") or 0
    return year * 10 + SEASON_RANK.get(record.get("s") or "", 0)


def count(conn) -> int:
    return conn.execute("SELECT count(*) FROM show_index").fetchone()[0]


def seed(conn, shows) -> int:
    """Replace the index with `shows`. Returns how many rows were written.

    A single COPY: 55,700 inserts one statement at a time takes minutes and
    this takes about a second.
    """
    conn.execute("TRUNCATE show_index")
    written = 0
    with conn.cursor().copy(
        "COPY show_index (collection_id, designer, season, year, gender, "
        "category, shoot_type, city, search_text, sort_rank) FROM STDIN"
    ) as copy:
        for r in shows:
            cid = r.get("c")
            if not cid:
                continue
            copy.write_row((
                cid, r.get("d"), r.get("s"), r.get("y"), r.get("g"),
                r.get("n"), r.get("t"), r.get("p"),
                search_text(r), sort_rank(r),
            ))
            written += 1
    return written


def upsert(conn, shows) -> int:
    """Add or update a handful of shows, for the incremental refresh."""
    written = 0
    for r in shows:
        cid = r.get("c")
        if not cid:
            continue
        conn.execute(
            """
            INSERT INTO show_index (collection_id, designer, season, year, gender,
                                    category, shoot_type, city, search_text, sort_rank)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (collection_id) DO UPDATE SET
                designer = EXCLUDED.designer, season = EXCLUDED.season,
                year = EXCLUDED.year, gender = EXCLUDED.gender,
                category = EXCLUDED.category, shoot_type = EXCLUDED.shoot_type,
                city = EXCLUDED.city, search_text = EXCLUDED.search_text,
                sort_rank = EXCLUDED.sort_rank
            """,
            (cid, r.get("d"), r.get("s"), r.get("y"), r.get("g"), r.get("n"),
             r.get("t"), r.get("p"), search_text(r), sort_rank(r)),
        )
        written += 1
    return written


def known_ids(conn) -> set:
    return {row[0] for row in conn.execute("SELECT collection_id FROM show_index").fetchall()}


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

_FILTER_COLUMNS = {
    "gender": "gender",
    "year": "year",
    "season": "season",
    "category": "category",
    "shootType": "shoot_type",
    "city": "city",
    "designer": "designer",
}


def _where(filters: dict, query: Optional[str]):
    """SQL fragment and parameters for a filter set plus a text query."""
    clauses, params = [], []

    for key, column in _FILTER_COLUMNS.items():
        value = (filters or {}).get(key)
        if value in (None, "", []):
            continue
        if key == "designer":
            clauses.append("lower(designer) = %s")
            params.append(str(value).lower())
        else:
            clauses.append(f"{column} = %s")
            params.append(int(value) if key == "year" else value)

    # The A-Z jump, which the indexed path would otherwise ignore in silence
    # — the worst way to handle a filter, since the list would look answered.
    letter = (filters or {}).get("letter")
    if letter:
        clauses.append("lower(designer) LIKE %s")
        params.append(f"{str(letter).lower()[:1]}%")

    # Every term must appear somewhere. "chanel fw25" is two terms, and a
    # show matches only if it answers both — which is what makes a two-word
    # query narrow rather than widen the result.
    for term in (normalise(query or "").split() if query else []):
        clauses.append("search_text LIKE %s")
        params.append(f"%{term}%")

    return (" AND ".join(clauses) if clauses else "TRUE"), params


def _row(r) -> dict[str, Any]:
    return {
        "collection_id": r[0], "designer": r[1], "season": r[2], "year": r[3],
        "gender": r[4], "category": r[5], "shoot_type": r[6], "city": r[7],
    }


def query(conn, *, filters=None, text=None, limit=100, offset=0) -> dict:
    """Shows matching a filter set and/or a text query, newest first."""
    where, params = _where(filters or {}, text)

    total = conn.execute(
        f"SELECT count(*) FROM show_index WHERE {where}", params
    ).fetchone()[0]

    rows = conn.execute(
        f"""
        SELECT collection_id, designer, season, year, gender, category,
               shoot_type, city
          FROM show_index
         WHERE {where}
         ORDER BY sort_rank DESC, lower(designer), collection_id
         LIMIT %s OFFSET %s
        """,
        params + [limit, offset],
    ).fetchall()

    return {"rows": [_row(r) for r in rows], "total": total,
            "hasMore": offset + len(rows) < total}


def facets(conn, *, filters=None, text=None) -> dict:
    """Which filter values are still reachable, and how many shows each has.

    Every dropdown is built from this, so the app can no longer offer a
    combination that returns nothing — and unlike the coverage catalog, the
    counts are exact rather than capped at one results page.
    """
    out = {}
    for key, column in (("year", "year"), ("season", "season"),
                        ("category", "category"), ("shootType", "shoot_type"),
                        ("gender", "gender"), ("city", "city")):
        # A facet's own value is dropped from the filters before counting it,
        # so choosing 2020 does not reduce the year list to just 2020.
        others = {k: v for k, v in (filters or {}).items() if k != key}
        where, params = _where(others, text)
        rows = conn.execute(
            f"""
            SELECT {column}, count(*) FROM show_index
             WHERE {where} AND {column} IS NOT NULL
             GROUP BY {column} ORDER BY count(*) DESC
            """,
            params,
        ).fetchall()
        out[key] = [{"value": r[0], "count": r[1]} for r in rows]
    return out


def designer_counts(conn, names) -> dict:
    """How many catalogue entries each named designer has.

    Entries, not distinct runway shows: firstVIEW lists a show once per
    shoot, so Chanel's number counts the Details and Atmosphere sets too.
    """
    wanted = [n for n in (names or []) if n]
    if not wanted:
        return {}
    rows = conn.execute(
        """
        SELECT lower(designer), count(*) FROM show_index
         WHERE lower(designer) = ANY(%s) GROUP BY lower(designer)
        """,
        ([n.lower() for n in wanted],),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def top_designers(conn, *, text=None, limit=8) -> list[dict]:
    """Designers whose names match, with their entry counts, most first."""
    term = normalise(text or "")
    if not term:
        return []
    rows = conn.execute(
        """
        SELECT designer, count(*) FROM show_index
         WHERE designer IS NOT NULL AND lower(designer) LIKE %s
         GROUP BY designer ORDER BY count(*) DESC, designer
         LIMIT %s
        """,
        (f"%{term}%", limit),
    ).fetchall()
    return [{"name": r[0], "count": r[1]} for r in rows]
