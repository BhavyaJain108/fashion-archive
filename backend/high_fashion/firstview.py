"""
firstVIEW collection source adapter.

Parses a firstVIEW collection page into structured looks and downloads
their images.

Page chain
----------
  collection_images.php?id={collection_id}
      -> one `div.thumbnailjt` per look, each holding:
           img.picture           src=/files/photo_thumbnail_{image_id}.jpg
           a.pictureinfo         data-content="<designer><br><category>
                                               <br><gender><br><season>"
           a[href]               collection_image_closeup.php?of={index}
                                   &collection={cid}&image={image_id}

  The mid-def image is derived directly from the image id:
      /files/photo_mid_def_{image_id}.jpg
  so the per-look closeup pages never need to be fetched. One request per
  collection, then one per image.

Access
------
This adapter is written for a personal, local archive with the rights
holder's permission. Two deliberate choices follow from that:

  * REQUEST_DELAY / MAX_WORKERS keep the crawl gentle. The legacy
    nowfashion path used 20 unthrottled threads; this does not.
  * Only the two resolutions the site itself serves in its viewer
    (thumbnail, mid_def) are requested. No probing for undisclosed
    higher-resolution assets.

Provenance (source URL, image id, fetch date) is written alongside the
files so the archive can always say where a picture came from.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict, field
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs, urljoin, quote_plus

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.firstview.com"

# Identify honestly rather than impersonating a browser.
USER_AGENT = "fashion-archive/1.0 (personal archive; +local)"

# Politeness knobs.
REQUEST_DELAY = 0.5   # seconds between image requests, per worker
MAX_WORKERS = 3       # concurrent image downloads
TIMEOUT = 30

QUALITY_THUMBNAIL = "thumbnail"
QUALITY_FULL = "full"

# Backwards-compatible alias — the legacy scheme's large size is "mid_def".
QUALITY_MID_DEF = QUALITY_FULL

# firstVIEW serves two asset schemes, and a collection uses one or the
# other depending on its vintage. Both are fully derivable from the
# collection page, so neither needs the per-look closeup pages.
#
#   legacy  /files/photo_thumbnail_{id}.jpg  ->  /files/photo_mid_def_{id}.jpg
#                                                423 x 634
#   hashed  /files/{cid}/thumb_{id}-{hash}.jpg -> /files/{cid}/{id}-{hash}.jpg
#                                                567 x 850
#
# The hash is opaque and identical across both sizes, so the large URL is
# the thumbnail URL minus its `thumb_` prefix. It cannot be guessed from
# an image id alone — it must come off the page.
SCHEME_LEGACY = "legacy"
SCHEME_HASHED = "hashed"

_LEGACY_THUMB_RE = re.compile(r"photo_thumbnail_(\d+)\.jpg", re.I)
_HASHED_THUMB_RE = re.compile(r"/files/(\d+)/thumb_((\d+)-[0-9a-f]+\.jpg)", re.I)

# ---------------------------------------------------------------------------
# Site vocabulary (see FIRSTVIEW.md). Read from the results page's own
# <select> elements — ids are not contiguous, so never generate ranges.
# ---------------------------------------------------------------------------

RESULTS_PER_PAGE = 20

SEASONS = {
    "Fall / Winter": "1",
    "Spring / Summer": "2",
    "Cruise": "3",
    "Prefall": "5",
}

CATEGORIES = {
    "Ready-to-Wear": "1",
    "Haute Couture": "2",
    "Swim": "3",
}

SHOOT_TYPES = {
    "Runway Collection": "7",
    "Runway Details": "4",
    "Runway Atmosphere": "11",
    "Backstage Beauty and Fashion": "3",
    "Lookbook": "8",
    "Bridal Collection": "5",
}

GENDERS = ("Women", "Men")

YEAR_MIN, YEAR_MAX = 1989, 2027

# div.collectTitle text. Two observed shapes:
#   "{Designer} - {Season} {Year} - {Gender}"
#   "{Designer} - {Year} - {Gender}"        (no season, e.g. Victoria's Secret)
# so the season group is optional.
_TITLE_RE = re.compile(
    r"^(?P<designer>.+?)\s+-\s+(?:(?P<season>\D+?)\s+)?(?P<year>\d{4})\s+-\s+(?P<gender>\w+)\s*$"
)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass
class Look:
    """One image within a collection."""

    image_id: str
    index: int                       # `of=` — the look's position, 0-based
    thumbnail_url: str
    full_url: str                    # largest size served without an account
    scheme: str = SCHEME_LEGACY      # SCHEME_LEGACY | SCHEME_HASHED
    closeup_url: Optional[str] = None
    designer: Optional[str] = None
    category: Optional[str] = None   # e.g. "Ready-to-Wear - Runway Collection"
    gender: Optional[str] = None
    season: Optional[str] = None


@dataclass
class Collection:
    """A firstVIEW collection page."""

    collection_id: str
    source_url: str
    designer: Optional[str] = None
    season: Optional[str] = None
    category: Optional[str] = None
    gender: Optional[str] = None
    looks: List[Look] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.looks)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def collection_id_from_url(url: str) -> Optional[str]:
    """Pull the `id` query param out of a collection_images.php URL."""
    qs = parse_qs(urlparse(url).query)
    vals = qs.get("id") or qs.get("collection")
    return vals[0] if vals else None


def collection_url(collection_id: str, all_looks: bool = True) -> str:
    """URL for one show.

    `list=all` is essential: without it the page returns only the first 20
    looks and gives no hint that more exist — a 161-look show silently
    looks like a 20-look show.
    """
    url = f"{BASE_URL}/collection_images.php?id={collection_id}"
    return url + "&list=all" if all_looks else url


def legacy_image_url(image_id: str, quality: str = QUALITY_FULL) -> str:
    """Build a legacy-scheme file URL for an image id.

    Only applies to collections using the `photo_*_{id}.jpg` layout; the
    hashed scheme cannot be constructed this way. Prefer reading URLs off
    the collection page via `parse_collection_page`.
    """
    if quality == QUALITY_THUMBNAIL:
        return f"{BASE_URL}/files/photo_thumbnail_{image_id}.jpg"
    if quality == QUALITY_FULL:
        return f"{BASE_URL}/files/photo_mid_def_{image_id}.jpg"
    raise ValueError(f"unsupported quality: {quality!r}")


# Kept for callers written against the pre-hashed-scheme API.
image_url = legacy_image_url


def _full_from_hashed_thumb(src: str) -> str:
    """`/files/{cid}/thumb_{id}-{hash}.jpg` -> the same path without `thumb_`."""
    return re.sub(r"/thumb_(?=[^/]+$)", "/", src)


def _parse_popover(data_content: str) -> Dict[str, Optional[str]]:
    """Parse the `.pictureinfo` popover into named fields.

    The popover is `<br>`-separated and ends with a "Full View / Zoom"
    anchor, which is dropped. Observed order is:
        designer, category, gender, season
    Shorter popovers are tolerated — missing trailing fields stay None.
    """
    soup = BeautifulSoup(data_content, "html.parser")
    for a in soup.find_all("a"):
        a.decompose()

    parts = [
        seg.strip()
        for seg in soup.decode().split("<br/>")
        if BeautifulSoup(seg, "html.parser").get_text(strip=True)
    ]
    parts = [BeautifulSoup(p, "html.parser").get_text(strip=True) for p in parts]

    keys = ("designer", "category", "gender", "season")
    out: Dict[str, Optional[str]] = {k: None for k in keys}
    for key, value in zip(keys, parts):
        out[key] = value or None
    return out


def parse_collection_page(html: bytes | str, source_url: str) -> Collection:
    """Parse a collection_images.php page into a Collection.

    Site chrome (`/themes/...` logos and social icons) is excluded by
    construction: only `img.picture` inside `.thumbnailjt` is considered.
    """
    soup = BeautifulSoup(html, "html.parser")
    cid = collection_id_from_url(source_url) or ""

    looks: List[Look] = []
    for block in soup.find_all(class_="thumbnailjt"):
        img = block.find("img", class_="picture")
        if not img:
            continue
        src = img.get("src") or ""

        # Which asset scheme is this collection on?
        hashed = _HASHED_THUMB_RE.search(src)
        legacy = None if hashed else _LEGACY_THUMB_RE.search(src)
        if hashed:
            image_id = hashed.group(3)
            scheme = SCHEME_HASHED
            full_src = _full_from_hashed_thumb(src)
        elif legacy:
            image_id = legacy.group(1)
            scheme = SCHEME_LEGACY
            full_src = f"/files/photo_mid_def_{image_id}.jpg"
        else:
            continue

        # The enlarge anchor carries the look's position.
        index = len(looks)
        closeup = None
        for a in block.find_all("a", href=True):
            href = a["href"]
            if "collection_image_closeup.php" in href:
                closeup = urljoin(BASE_URL + "/", href)
                of = parse_qs(urlparse(href).query).get("of")
                if of and of[0].isdigit():
                    index = int(of[0])
                break

        meta: Dict[str, Optional[str]] = {
            "designer": None, "category": None, "gender": None, "season": None,
        }
        info = block.find(class_="pictureinfo")
        if info and info.get("data-content"):
            meta = _parse_popover(info["data-content"])

        looks.append(Look(
            image_id=image_id,
            index=index,
            thumbnail_url=urljoin(BASE_URL, src),
            full_url=urljoin(BASE_URL, full_src),
            scheme=scheme,
            closeup_url=closeup,
            **meta,
        ))

    looks.sort(key=lambda l: l.index)

    collection = Collection(collection_id=cid, source_url=source_url, looks=looks)

    # Collection-level fields: prefer the page's own season element, then
    # fall back to whatever the looks agree on.
    season_el = soup.find(class_="season")
    if season_el:
        collection.season = season_el.get_text(strip=True) or None

    for attr in ("designer", "season", "category", "gender"):
        if getattr(collection, attr):
            continue
        values = {getattr(l, attr) for l in looks if getattr(l, attr)}
        if len(values) == 1:
            setattr(collection, attr, values.pop())

    return collection


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _session(user_agent: str = USER_AGENT) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,image/webp,*/*;q=0.8",
    })
    return s


def fetch_collection(
    collection: str,
    session: Optional[requests.Session] = None,
) -> Collection:
    """Fetch and parse one collection. `collection` is an id or a full URL."""
    cid = collection_id_from_url(collection) if "://" in collection else collection
    if not cid:
        raise ValueError(f"could not determine collection id from {collection!r}")

    url = collection_url(cid)
    sess = session or _session()
    resp = sess.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return parse_collection_page(resp.content, url)


def iter_download_collection(
    collection: "str | Collection",
    out_root: "str | Path",
    quality: str = QUALITY_FULL,
    session: Optional[requests.Session] = None,
    max_workers: int = MAX_WORKERS,
    delay: float = REQUEST_DELAY,
):
    """Download a show, yielding events as it goes.

    Yields, in order:
        ("meta",  {designer, season, count, looks, cache_dir})
        ("image", {path, url, index, filename, cached})   x count
        ("error", {url, index, error})                    on failure
        ("done",  {count, failed, cache_dir, ...})

    The meta event carries every look's metadata before a single image has
    landed, so a client can lay out the full grid immediately and fill it
    in as images arrive. A 264-look show otherwise shows nothing for a
    minute.
    """
    from concurrent.futures import ThreadPoolExecutor

    sess = session or _session()
    coll = collection if isinstance(collection, Collection) else fetch_collection(collection, sess)

    out_dir = Path(out_root) / _collection_slug(coll)
    out_dir.mkdir(parents=True, exist_ok=True)

    yield "meta", {
        "designer": coll.designer,
        "season": coll.season,
        "gender": coll.gender,
        "category": coll.category,
        "collection_id": coll.collection_id,
        "count": coll.count,
        "cache_dir": str(out_dir.resolve()),
        "looks": [asdict(l) for l in coll.looks],
    }

    results: List[Dict] = []
    failures: List[Dict] = []

    def fetch_one(look: Look) -> Dict:
        url = look.thumbnail_url if quality == QUALITY_THUMBNAIL else look.full_url
        filename = f"{look.index:03d}_{look.image_id}.jpg"
        path = out_dir / filename
        try:
            if path.exists() and path.stat().st_size > 0:
                return {"ok": True, "path": str(path.resolve()), "url": url,
                        "index": look.index, "filename": filename, "cached": True}
            time.sleep(delay)
            r = sess.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            path.write_bytes(r.content)
            return {"ok": True, "path": str(path.resolve()), "url": url,
                    "index": look.index, "filename": filename, "cached": False}
        except Exception as e:  # noqa: BLE001 — report per image, keep going
            return {"ok": False, "url": url, "index": look.index, "error": str(e)}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # imap-style: results stream back in completion order.
        for res in pool.map(fetch_one, coll.looks):
            if res.pop("ok"):
                results.append(res)
                yield "image", res
            else:
                failures.append(res)
                yield "error", res

    results.sort(key=lambda r: r["index"])
    _write_manifest(out_dir, coll, quality)

    yield "done", {
        "images": results,
        "count": len(results),
        "failed": failures,
        "cache_dir": str(out_dir.resolve()),
        "designer": coll.designer,
        "season": coll.season,
        "success": len(results) > 0,
    }


def download_collection(
    collection: "str | Collection",
    out_root: "str | Path",
    quality: str = QUALITY_FULL,
    session: Optional[requests.Session] = None,
    max_workers: int = MAX_WORKERS,
    delay: float = REQUEST_DELAY,
    progress=None,
) -> Dict:
    """Download every look in a show. Blocking wrapper around
    `iter_download_collection`; returns its final "done" payload."""
    final: Dict = {}
    done = 0
    for kind, payload in iter_download_collection(
        collection, out_root, quality=quality, session=session,
        max_workers=max_workers, delay=delay,
    ):
        if kind == "image":
            done += 1
            if progress:
                progress(done, None)
        elif kind == "done":
            final = payload
    return final


def _collection_slug(coll: Collection) -> str:
    """Directory name for a show.

    A designer can have several shows with identical designer+season+gender
    (firstVIEW splits some across collection ids), so the id is part of the
    name — without it those shows overwrite each other.
    """
    slug = _slugify(coll.designer or "collection")
    if coll.season:
        slug = f"{slug}_{_slugify(coll.season)}"
    return f"{slug}_{coll.collection_id}"


def _write_manifest(out_dir: Path, coll: Collection, quality: str) -> None:
    manifest = {
        "collection": {k: v for k, v in asdict(coll).items() if k != "looks"},
        "looks": [asdict(l) for l in coll.looks],
        "fetched_on": date.today().isoformat(),
        "quality": quality,
        "source": "firstview.com",
    }
    (out_dir / "collection.json").write_text(json.dumps(manifest, indent=2))


# ---------------------------------------------------------------------------
# Browse / search
# ---------------------------------------------------------------------------

@dataclass
class CollectionSummary:
    """One row of a results page — a show, without its looks."""

    collection_id: str
    url: str
    title: str
    designer: Optional[str] = None
    season: Optional[str] = None
    year: Optional[int] = None
    gender: Optional[str] = None
    # From p.collecInfo on the row: category, shoot type and city are all
    # printed per row, so none of them need a separate filtered crawl.
    category: Optional[str] = None      # span.nature — Ready-to-Wear, ...
    shoot_type: Optional[str] = None    # span.type   — Runway Collection, ...
    city: Optional[str] = None          # span.place  — Milan, ...
    look_count: Optional[int] = None    # filled in only to break ties


def build_search_url(
    gender: Optional[str] = None,
    year: Optional[int] = None,
    season: Optional[str] = None,
    category: Optional[str] = None,
    shoot_type: Optional[str] = None,
    city_id: Optional[str] = None,
    letter: Optional[str] = None,
    page: int = 0,
    sort: str = "date",
) -> str:
    """Build a collection_results.php URL.

    `season`, `category` and `shoot_type` accept either the human label
    ("Fall / Winter") or the site's raw id ("1").
    """
    def code(value, table):
        if value is None:
            return None
        return table.get(value, value)

    params: Dict[str, str] = {}
    if gender:
        params["s_g"] = gender
    if year:
        params["filter_year"] = str(year)
    if season:
        params["filter_season"] = code(season, SEASONS)
    if category:
        params["s_n"] = code(category, CATEGORIES)
    if shoot_type:
        params["s_t"] = code(shoot_type, SHOOT_TYPES)
    if city_id:
        params["s_p"] = str(city_id)
    if letter:
        params["l"] = letter.upper()
    if sort:
        params["b"] = sort
    if page:
        params["page"] = str(page)

    query = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    return f"{BASE_URL}/collection_results.php?{query}"


def parse_results_page(html: bytes | str) -> List[CollectionSummary]:
    """Parse collection_results.php into show summaries.

    Designer / season / year / gender come from the row title, so a listing
    is fully described without opening each show.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: List[CollectionSummary] = []
    seen = set()

    for node in soup.find_all(class_="collectTitle"):
        a = node.find("a", href=True) if node.name != "a" else node
        if not a or "collection_images.php" not in a["href"]:
            continue
        cid = collection_id_from_url(a["href"])
        if not cid or cid in seen:
            continue
        seen.add(cid)

        title = node.get_text(" ", strip=True)
        summary = CollectionSummary(
            collection_id=cid,
            url=collection_url(cid),
            title=title,
        )

        # p.collecInfo sits alongside the title in the row container and
        # carries the three fields that distinguish otherwise identical
        # rows — a designer often has several shows in one season.
        row = node.parent
        if row:
            info = row.find(class_="collecInfo")
            if info:
                for attr, cls in (("category", "nature"),
                                  ("shoot_type", "type"),
                                  ("city", "place")):
                    el = info.find(class_=cls)
                    if el:
                        setattr(summary, attr, el.get_text(strip=True) or None)
        m = _TITLE_RE.match(title)
        if m:
            summary.designer = m.group("designer").strip()
            season = m.group("season")          # optional — absent on some shows
            summary.season = season.strip() if season else None
            summary.year = int(m.group("year"))
            summary.gender = m.group("gender").strip()
        out.append(summary)

    return out


def iter_search_collections(
    session: Optional[requests.Session] = None,
    max_pages: int = 1,
    delay: float = REQUEST_DELAY,
    **filters,
):
    """Yield each results page as it arrives.

    A season can run to 30+ pages; collecting them all before returning
    means ~35 s of nothing. Callers that can render incrementally should
    use this and let rows appear as they land.
    """
    sess = session or _session()
    seen = set()

    for page in range(max_pages):
        url = build_search_url(page=page, **filters)
        resp = sess.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        rows = parse_results_page(resp.content)

        fresh = [r for r in rows if r.collection_id not in seen]
        if not fresh:
            return
        seen.update(r.collection_id for r in fresh)
        yield fresh

        if len(rows) < RESULTS_PER_PAGE:
            return
        if page + 1 < max_pages:
            time.sleep(delay)


def search_collections(
    session: Optional[requests.Session] = None,
    max_pages: int = 1,
    delay: float = REQUEST_DELAY,
    **filters,
) -> List[CollectionSummary]:
    """Run a results query, following up to `max_pages` pages.

    Blocking wrapper around `iter_search_collections` — same crawl, but
    returns only once every page is in.
    """
    results: List[CollectionSummary] = []
    for batch in iter_search_collections(
        session=session, max_pages=max_pages, delay=delay, **filters
    ):
        results.extend(batch)
    return results


@dataclass
class Designer:
    designer_id: str
    name: str
    url: str


def list_designers(
    letter: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> List[Designer]:
    """Designers from alpha_list.php. `letter` A-Z; omit for the first page
    (symbols and A)."""
    params = "type=designer&deslist=1"
    if letter:
        params += f"&l={letter.upper()}"
    sess = session or _session()
    resp = sess.get(f"{BASE_URL}/alpha_list.php?{params}", timeout=TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        if "collection_designer.php" not in a["href"]:
            continue
        sd = parse_qs(urlparse(a["href"]).query).get("s_d", [None])[0]
        name = a.get_text(strip=True)
        if not sd or not name or sd in seen:
            continue
        seen.add(sd)
        out.append(Designer(sd, name, f"{BASE_URL}/collection_designer.php?s_d={sd}"))
    return out


def designer_collections(
    designer_id: str,
    session: Optional[requests.Session] = None,
    max_pages: int = 100,
    delay: float = REQUEST_DELAY,
) -> List[CollectionSummary]:
    """Every show by one designer, across all years and genders.

    collection_designer.php paginates with a 0-based `page` param at
    RESULTS_PER_PAGE rows — a prolific designer runs to many pages, so this
    follows them all rather than returning only the first.
    """
    sess = session or _session()
    results: List[CollectionSummary] = []
    seen = set()

    for page in range(max_pages):
        url = f"{BASE_URL}/collection_designer.php?s_d={designer_id}"
        if page:
            url += f"&page={page}"
        resp = sess.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        rows = parse_results_page(resp.content)

        fresh = [r for r in rows if r.collection_id not in seen]
        if not fresh:
            break
        seen.update(r.collection_id for r in fresh)
        results.extend(fresh)

        if len(rows) < RESULTS_PER_PAGE:
            break
        if page + 1 < max_pages:
            time.sleep(delay)

    return results


# No implicit shoot-type filter. Defaulting to "Runway Collection" once
# looked like a tidy way to stop a designer appearing several times per
# season, but it hid every show catalogued only as Runway Details — Men
# RTW FW2026 showed 31 of 44, and Paul Smith, Pronounce and Yohji Yamamoto
# disappeared outright. Rows carry their own shoot type now, so duplicates
# are labelled instead of dropped.
DEFAULT_SHOOT_TYPE = None


def fill_look_counts(
    rows: List[CollectionSummary],
    session: Optional[requests.Session] = None,
    delay: float = REQUEST_DELAY,
) -> None:
    """Set `look_count` on rows that are otherwise indistinguishable.

    A designer can have two shows in one season with identical designer,
    category, shoot type and city — Gucci FW2025 Women is 56627 and 56631,
    which share every printed field but hold 286 and 228 different looks.
    Nothing on the results page separates them, so the count is fetched,
    but only for the colliding rows: a season of 250 shows typically has a
    handful.

    Mutates `rows` in place.
    """
    from collections import defaultdict

    groups = defaultdict(list)
    for r in rows:
        groups[(r.designer, r.season, r.year, r.gender,
                r.category, r.shoot_type, r.city)].append(r)

    sess = session or _session()
    for group in groups.values():
        if len(group) < 2:
            continue
        for r in group:
            try:
                r.look_count = fetch_collection(r.collection_id, sess).count
                time.sleep(delay)
            except Exception:  # noqa: BLE001 — a missing count just means no suffix
                pass


def category_map(
    session: Optional[requests.Session] = None,
    max_pages: int = 60,
    **filters,
) -> Dict[str, str]:
    """Map collection_id -> category for one query.

    A results row shows only "{Designer} - {Season} {Year} - {Gender}", so
    a designer showing both Ready-to-Wear and Haute Couture in the same
    season renders as two identical rows. Category is only expressible as
    a filter, so it is recovered by re-running the query per category.

    Only the small categories are crawled (Haute Couture, Swim); anything
    not in the result is Ready-to-Wear, which is the bulk. That costs two
    extra crawls rather than one per category.
    """
    sess = session or _session()
    # The caller's own `category` is what we're resolving; drop it so it
    # doesn't collide with the per-category value below.
    filters = {k: v for k, v in filters.items() if k != "category"}

    out: Dict[str, str] = {}
    for label in ("Haute Couture", "Swim"):
        for r in search_collections(
            session=sess, max_pages=max_pages, category=label, **filters
        ):
            out[r.collection_id] = label
    return out


COVERAGE_VERSION = 1


def coverage_key(year: int, season: str, gender: str) -> str:
    return f"{year}|{season}|{gender}"


def build_coverage(
    out_path: "str | Path",
    shoot_type: Optional[str] = DEFAULT_SHOOT_TYPE,
    delay: float = REQUEST_DELAY,
    session: Optional[requests.Session] = None,
    progress=None,
) -> Dict:
    """Probe every year × season × gender and record what actually exists.

    The filter UI otherwise offers combinations that return nothing —
    firstVIEW has no Men before ~2000, no Cruise for Men in most years, and
    Prefall is sparse throughout. One page-0 request per combination is
    enough to tell empty from non-empty.

    Categories are probed only where the combination is non-empty, which
    prunes most of the work: an empty year × season × gender costs one
    request instead of four.

    Counts are page-0 counts, so they saturate at RESULTS_PER_PAGE — they
    say "at least this many", and 0 is the only exact value. That is all
    the UI needs to enable or disable an option.

    The result is committed to backend/high_fashion/coverage.json so it
    ships with the image; it is derived data, but re-deriving it costs ~880
    requests to someone else's site and only changes when a season is added.
    """
    sess = session or _session()
    combos: Dict[str, Dict] = {}

    todo = [(y, s, g)
            for y in range(YEAR_MAX, YEAR_MIN - 1, -1)
            for s in SEASONS
            for g in GENDERS]

    for i, (year, season, gender) in enumerate(todo):
        try:
            rows = search_collections(
                session=sess, max_pages=1, gender=gender, year=year,
                season=season, shoot_type=shoot_type,
            )
        except Exception:  # noqa: BLE001 — a failed probe is "unknown", not "empty"
            rows = None

        entry: Dict[str, object] = {
            "hint": len(rows) if rows is not None else None,
            "categories": {},
        }

        if rows:
            for label in CATEGORIES:
                time.sleep(delay)
                try:
                    got = search_collections(
                        session=sess, max_pages=1, gender=gender, year=year,
                        season=season, shoot_type=shoot_type, category=label,
                    )
                    entry["categories"][label] = len(got)
                except Exception:  # noqa: BLE001
                    entry["categories"][label] = None

        combos[coverage_key(year, season, gender)] = entry
        if progress:
            progress(i + 1, len(todo), year, season, gender, entry["hint"])
        time.sleep(delay)

    data = {
        "version": COVERAGE_VERSION,
        "built_on": date.today().isoformat(),
        "shoot_type": shoot_type,
        "combos": combos,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2))
    return data


def load_coverage(path: "str | Path") -> Optional[Dict]:
    """Read a coverage file, or None if it is missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001
        return None
    return data if data.get("version") == COVERAGE_VERSION else None


def available_seasons() -> List[Dict[str, object]]:
    """Every season the archive offers, newest first.

    Derived from the site's own year range and season vocabulary rather
    than crawled — the results page exposes both as select options.
    """
    return [
        {"year": year, "season": label, "season_id": sid}
        for year in range(YEAR_MAX, YEAR_MIN - 1, -1)
        for label, sid in SEASONS.items()
    ]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[\s_-]+", "_", slug) or "untitled"
