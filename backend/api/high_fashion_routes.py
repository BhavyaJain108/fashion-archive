"""
High Fashion API Routes
========================

Endpoints backed by firstVIEW (see backend/high_fashion/FIRSTVIEW.md):
- Seasons listing
- Collections by season
- Images download
- Video streaming
"""

from flask import jsonify, request, send_file, Response

import gzip
import json
import shutil
import tempfile

from backend.storage import images
from backend.auth import db
from backend.auth.middleware import current_user
from backend.high_fashion import collection_cache
from backend.userdata import recents
import os
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, quote, urlparse
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Legacy header block; firstview.py sets its own session headers.
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# Which year/season/gender/category combinations actually have shows.
# Built by firstview.build_coverage. Committed rather than left in cache/,
# which is gitignored and so would never reach the image — in production
# load_coverage would return None and every dead filter option would become
# clickable again. Absent, every option stays selectable, which is the safe
# direction: a dead end beats hiding real shows.
COVERAGE_PATH = "backend/high_fashion/coverage.json"


def get_seasons():
    """POST /api/seasons - List every season firstVIEW offers.

    A firstVIEW "season" is the triple (year, season, gender); there is no
    season landing page, so `url` carries a collection_results.php query
    that /api/collections reads back. Structured fields are returned
    alongside `name` so clients don't have to parse the label.
    """
    try:
        from backend.high_fashion import firstview as fv

        coverage = fv.load_coverage(COVERAGE_PATH) or {}
        combos = coverage.get('combos', {})

        seasons = []
        for year in range(fv.YEAR_MAX, fv.YEAR_MIN - 1, -1):
            for label, sid in fv.SEASONS.items():
                for gender in fv.GENDERS:
                    url = fv.build_search_url(gender=gender, year=year, season=label)
                    entry = combos.get(fv.coverage_key(year, label, gender))

                    # With no coverage file every option stays selectable —
                    # better to offer a dead end than to hide real shows.
                    if entry is None:
                        available, categories = True, None
                    else:
                        available = bool(entry.get('hint'))
                        categories = entry.get('categories') or {}

                    seasons.append({
                        'name': f'{label} {year} - {gender}',
                        'url': url,
                        'href': url.replace(fv.BASE_URL, ''),
                        # structured — preferred over parsing `name`
                        'year': year,
                        'season': label,
                        'season_id': sid,
                        'gender': gender,
                        'available': available,
                        'categories': categories,
                    })

        return jsonify({
            'seasons': seasons,
            'coverage_built_on': coverage.get('built_on'),
            'success': True,
        })

    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500


def _season_filters(q, data):
    """Filters for a season query, from the seasonUrl's params.

    No shoot type is applied unless the client asks: filtering to Runway
    Collection hid shows that only exist as Runway Details. Rows are
    labelled with their shoot type instead, so repeats stay tellable apart.
    """
    from backend.high_fashion import firstview as fv
    one = lambda k: q.get(k, [None])[0]
    shoot_type = data.get('shootType', one('s_t'))
    return dict(
        gender=one('s_g'),
        year=int(one('filter_year')) if one('filter_year') else None,
        season=one('filter_season'),
        category=data.get('category', one('s_n')),
        shoot_type=shoot_type or None,
        city_id=one('s_p'),
        letter=one('l'),
    )


# Season names are long and the subtitle carries five other fields; the
# abbreviations are the ones the industry already uses.
_SEASON_SHORT = {
    'Fall / Winter': 'F/W',
    'Spring / Summer': 'S/S',
}

# The subtitle now carries six fields in one line of a 320px column, so the
# long-form names are abbreviated to the trade's own shorthand. Without this
# the city — often the only thing separating two rows — was the field that
# got ellipsised off the end.
_CATEGORY_SHORT = {
    'Ready-to-Wear': 'RTW',
    'Haute Couture': 'Couture',
}

_SHOOT_SHORT = {
    'Runway Details': 'Details',
    'Runway Atmosphere': 'Atmosphere',
    'Backstage Beauty and Fashion': 'Backstage',
    'Bridal Collection': 'Bridal',
}


def _row_to_dict(r):
    """One results row, with a label that distinguishes near-identical shows.

    A designer often appears several times in one season. The row itself
    carries category / shoot type / city, and where even those match,
    `look_count` has been filled in to break the tie — so the list never
    shows the same name twice with nothing to tell them apart.
    """
    name = r.designer or r.title

    # Everything that is not the brand name goes in the subtitle, including
    # season and year. The list is no longer filtered down to one season
    # before you can see it, so a row has to say for itself which show it is.
    bits = []
    if r.season and r.year:
        bits.append(f'{_SEASON_SHORT.get(r.season, r.season)} {r.year}')
    elif r.year:
        bits.append(str(r.year))
    if r.gender:
        bits.append(r.gender)
    if r.category:
        bits.append(_CATEGORY_SHORT.get(r.category, r.category))
    # Runway Collection is the plain case and is left unsaid; naming it on
    # nine rows in ten would push the fields that differ off the line.
    if r.shoot_type and r.shoot_type != 'Runway Collection':
        bits.append(_SHOOT_SHORT.get(r.shoot_type, r.shoot_type))
    if r.city:
        bits.append(r.city)
    if r.look_count:
        bits.append(f'{r.look_count} looks')

    # The brand stands alone; the qualifier goes underneath it in the list,
    # so a narrow column doesn't truncate away the very thing that tells
    # two rows of the same brand apart.
    return {
        'designer': name,
        'subtitle': ' · '.join(bits),
        'url': r.url,
        'text': r.title,
        'photos': '', 'date': '',
        'collection_id': r.collection_id,
        'season': r.season,
        'year': r.year,
        'gender': r.gender,
        'category': r.category,
        'shoot_type': r.shoot_type,
        'city': r.city,
        'look_count': r.look_count,
        'designer_name': r.designer,
    }


def get_collections():
    """POST /api/collections - Shows for a season.

    `seasonUrl` is a collection_results.php URL as handed out by
    /api/seasons; its query params are read back and re-run. Pages through
    the full result set, so a big season returns hundreds of shows.
    """
    try:
        from urllib.parse import urlparse, parse_qs
        from backend.high_fashion import firstview as fv

        data = request.get_json() or {}
        season_url = data.get('seasonUrl', '')
        if not season_url:
            return jsonify({'error': 'seasonUrl is required', 'success': False}), 400

        q = parse_qs(urlparse(season_url).query)
        one = lambda k: q.get(k, [None])[0]

        filters = _season_filters(q, data)
        max_pages = int(data.get('maxPages', 60))

        rows = fv.search_collections(max_pages=max_pages, **filters)
        fv.fill_look_counts(rows)
        collections = [_row_to_dict(r) for r in rows]

        return jsonify({'collections': collections, 'success': True})

    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500


def extract_look_number(img):
    """Look number from a filename like '...-0007.jpg'. Runway images are
    meaningless out of order, and the source sorts by name, not by look."""
    match = re.search(r'-(\d+)\.', img['filename'])
    return int(match.group(1)) if match else 0


def _upload_images(store, designer_name, entries):
    """Upload the kept images and return them with browser-loadable URLs.

    Called after filtering rather than during download, so images the organizer
    discards are never stored.
    """
    uploaded = []
    for entry in entries:
        try:
            data = Path(entry['local_path']).read_bytes()
        except OSError as exc:
            print(f"Failed to read {entry['local_path']}: {exc}")
            continue

        key = images.runway_key(designer_name, entry['filename'])
        uploaded.append({
            # A URL now, not a filesystem path. It used to be an absolute path
            # the client handed back to /api/image?path= for the server to read
            # off disk — meaningless on another machine, and that endpoint read
            # whatever path it was given.
            'path': store.save(key, data),
            # Kept so cache eviction can delete the object, not just the row.
            'key': key,
            'source_url': entry['source_url'],
            'index': entry['index'],
            'filename': entry['filename'],
            'success': True,
        })
    return uploaded


# Uploads run on our own bucket, so unlike fetching from firstVIEW there is
# no politeness budget to respect — the only limit is how many sockets are
# worth holding open. Measured on this bucket: one upload is ~0.47s, twelve
# at a time clear ~16 a second.
UPLOAD_WORKERS = 12


def _upload_one(store, designer_name, entry):
    """Upload one downloaded look. Returns its entry, or None if it failed.

    Runs on a worker thread, so it raises nothing: a single unreadable file
    must not take down the show around it.
    """
    try:
        data = Path(entry['local_path']).read_bytes()
    except OSError as exc:
        print(f"Failed to read {entry['local_path']}: {exc}")
        return None

    key = images.runway_key(designer_name, entry['filename'])
    try:
        url = store.save(key, data)
    except Exception as exc:  # noqa: BLE001 — one lost look, not a lost show
        print(f"Failed to upload {key}: {exc}")
        return None

    return {
        'path': url,
        'key': key,
        'source_url': entry['source_url'],
        'index': entry['index'],
        'filename': entry['filename'],
        'success': True,
    }


def _record_recent(collection_id, payload, images_list=None):
    """Note that the signed-in user opened this show.

    Best effort: a history entry is never worth failing a download over, and
    an unauthenticated or partially-loaded request simply records nothing.
    """
    try:
        user = current_user()
        if user is None:
            return
        thumb = None
        if images_list:
            first = min(images_list, key=lambda i: i.get('index', 0))
            thumb = first.get('path')
        with db.transaction() as conn:
            recents.record(
                conn,
                user_id=user.id,
                collection_id=collection_id,
                designer=payload.get('designer') or 'Unknown',
                collection_url=payload.get('source_url')
                    or f"https://www.firstview.com/collection_images.php?id={collection_id}",
                season=payload.get('season'),
                gender=payload.get('gender'),
                thumbnail_url=thumb,
                look_count=payload.get('count') or payload.get('look_count'),
            )
    except Exception as exc:  # noqa: BLE001
        print(f"recents: could not record {collection_id}: {exc}")


def _cache_lookup(collection_id, quality):
    """A previously stored show, or None. Never raises: a cache that is down
    should make things slow, not broken.

    An entry holding no images counts as a miss, and is dropped. Shows whose
    looks all failed to download used to be stored as empty and then replayed
    from that empty entry for good — so a show broken once stayed broken even
    after the cause was fixed. Treating it as a miss lets those heal on the
    next open rather than needing anything run against the database.
    """
    try:
        with db.transaction() as conn:
            hit = collection_cache.get(conn, collection_id=collection_id, quality=quality)
            if hit and not hit.get('images'):
                print(f"cache: dropping empty entry for {collection_id}")
                collection_cache.forget(conn, collection_id=collection_id)
                return None
            if hit:
                collection_cache.touch(conn, collection_id=collection_id)
            return hit
    except Exception as exc:  # noqa: BLE001
        print(f"cache lookup failed for {collection_id}: {exc}")
        return None


def _cache_store(collection_id, quality, uploaded, meta, store):
    """Record a freshly fetched show, then trim the cache to its limit.

    A show that produced no images is not recorded. There is nothing to serve
    from it, and storing it would turn one bad fetch into a permanent empty
    show — the next open should try again.
    """
    if not uploaded:
        print(f"cache: not storing {collection_id}, no images were downloaded")
        return
    try:
        with db.transaction() as conn:
            collection_cache.put(
                conn,
                collection_id=collection_id,
                quality=quality,
                images=uploaded,
                designer=meta.get('designer'),
                season=meta.get('season'),
                gender=meta.get('gender'),
                category=meta.get('category'),
                shoot_type=meta.get('shoot_type'),
            )
            evicted = collection_cache.evict(conn, store)
            if evicted:
                print(f"cache: evicted {evicted} show(s) past the limit")
    except Exception as exc:  # noqa: BLE001
        print(f"cache store failed for {collection_id}: {exc}")


def download_images():
    """POST /api/download-images - Download every look in one show.

    `collectionUrl` is a collection_images.php URL (or a bare id).

    Images are fetched into a temp directory and uploaded to the image
    store, which returns browser-loadable URLs; the temp directory is
    removed in the finally below, so a failed run cannot leave the
    container's disk filling up. `path` on each entry is a URL, not a
    filesystem path.

    There is no organizer pass here. It existed to sift runway looks out of
    a page that also carried logos, ad pixels and avatars; firstVIEW returns
    the collection's looks and nothing else, so there is nothing to discard.
    """
    temp_dir = None
    try:
        from backend.high_fashion import firstview as fv

        data = request.get_json() or {}
        collection_url = data.get('collectionUrl', '')
        if not collection_url:
            return jsonify({'error': 'collectionUrl is required', 'success': False}), 400

        quality = data.get('quality', fv.QUALITY_FULL)
        collection_id = fv.collection_id_from_url(collection_url) or collection_url

        # Already in R2? Hand back the stored URLs and make no request to
        # firstVIEW at all.
        hit = _cache_lookup(collection_id, quality)
        if hit:
            _record_recent(collection_id, hit, hit['images'])
            return jsonify({
                'success': True,
                'images': hit['images'],
                'count': len(hit['images']),
                'failed': [],
                'designer': hit.get('designer'),
                'season': hit.get('season'),
                'cached': True,
            })

        store = images.get_store()
        temp_dir = tempfile.mkdtemp(prefix='runway_')

        result = fv.download_collection(
            collection_url,
            out_root=temp_dir,
            quality=quality,
        )

        designer_name = data.get('designerName') or result.get('designer') or 'unknown'
        entries = [{
            'local_path': img['path'],
            'source_url': img['url'],
            'index': img['index'],
            'filename': img['filename'],
        } for img in result.get('images', [])]

        uploaded = _upload_images(store, designer_name, entries)
        _cache_store(collection_id, quality, uploaded, result, store)
        _record_recent(collection_id, result, uploaded)

        return jsonify({
            'success': bool(uploaded),
            'images': uploaded,
            'count': len(uploaded),
            'failed': result.get('failed', []),
            'designer': result.get('designer'),
            'season': result.get('season'),
            'cached': False,
        })

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR in download_images: {error_details}")
        return jsonify({'error': str(e), 'traceback': error_details, 'success': False}), 500
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def serve_stored_image(key):
    """GET /api/images/<key> - serve an image from the local store.

    Development only. In production images live in R2 and are served from
    images.premiumpropogandafashion.studio, so this endpoint is never hit.

    It replaces `/api/image?path=<absolute path>`, which took a filesystem path
    from the client and read whatever it pointed at. Here the client names a key
    inside the store, and the store refuses keys that escape its root.
    """
    store = images.get_store()
    if not isinstance(store, images.LocalImageStore):
        return jsonify({'error': 'images are served from the CDN'}), 404

    try:
        data = store.read(key)
    except ValueError:
        return jsonify({'error': 'invalid image key'}), 400

    if data is None:
        return jsonify({'error': 'image not found'}), 404

    return Response(data, mimetype=images.guess_content_type(key))


def _sse(payload: dict) -> str:
    """One Server-Sent Event frame."""
    import json as _json
    return f"data: {_json.dumps(payload)}\n\n"


def stream_collections():
    """POST /api/collections/stream - shows for a season, as they are found.

    Emits one {type:'collections'} event per results page, then
    {type:'done'}. A big season is 30+ pages; this puts the first 20 rows
    on screen in well under a second instead of after the whole crawl.
    """
    from urllib.parse import urlparse, parse_qs
    from backend.high_fashion import firstview as fv

    # Request context is gone inside the generator, so read params now.
    data = request.get_json() or {}
    season_url = data.get('seasonUrl', '')
    if not season_url:
        return jsonify({'error': 'seasonUrl is required', 'success': False}), 400

    q = parse_qs(urlparse(season_url).query)
    filters = _season_filters(q, data)
    max_pages = int(data.get('maxPages', 60))

    def generate():
        total = 0
        try:
            seen = []
            for batch in fv.iter_search_collections(max_pages=max_pages, **filters):
                seen.extend(batch)
                rows = [_row_to_dict(r) for r in batch]
                total += len(rows)
                yield _sse({'type': 'collections', 'collections': rows, 'total': total})
            # Breaking ties costs one request per colliding row, so it runs
            # after everything is on screen: the list stays fast, and the
            # few ambiguous rows get their look counts a moment later.
            fv.fill_look_counts(seen)
            relabelled = {r.collection_id: _row_to_dict(r)['designer']
                          for r in seen if r.look_count}
            if relabelled:
                yield _sse({'type': 'relabel', 'labels': relabelled})

            yield _sse({'type': 'done', 'total': total, 'success': True})
        except Exception as e:
            yield _sse({'type': 'error', 'error': str(e), 'success': False})

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def _number_ties(rows):
    """Number rows that even a look count cannot tell apart.

    firstVIEW catalogues some shows twice — Carrieri F/W 2026 is 57796 and
    57797, both Women, RTW, Barcelona, both 72 looks. They are not
    duplicates: the two sets share not one image, so dropping either would
    hide 72 photographs. What they lack is anything printed that differs,
    which is what made the list look like it was repeating itself.

    Mutates `rows` in place.
    """
    from collections import defaultdict

    groups = defaultdict(list)
    for row in rows:
        groups[(row['designer'], row['subtitle'])].append(row)

    for group in groups.values():
        if len(group) < 2:
            continue
        for n, row in enumerate(group, 1):
            row['subtitle'] = f"{row['subtitle']} · set {n}"


def stream_catalog():
    """POST /api/catalog/stream - a window of the archive, as it is found.

    The browsing endpoint. Unlike /api/collections it takes no seasonUrl and
    requires nothing but a gender: firstVIEW answers a gender-only query with
    every show it holds for that gender, newest first, which is what lets the
    app open on the whole archive instead of making you pick a year, then a
    season, then a gender before it will show you anything.

    Every other filter — year, season, category, shoot type, city, initial —
    is optional and simply narrows the same query.

    Gender is the one axis that cannot be left out. A completely unfiltered
    query does not mean "everything"; it returns a 34-row bucket of shows
    catalogued with no gender at all.

    Paged by request: `startPage` and `pages` read a window, and `done`
    carries `nextPage`/`hasMore` so the client can ask for the next one when
    the reader nears the bottom. Reading it all eagerly would be 900+
    requests to someone else's site for a list nobody scrolls to the end of.
    """
    from backend.high_fashion import firstview as fv

    data = request.get_json() or {}

    filters = dict(
        gender=data.get('gender') or 'Women',
        year=int(data['year']) if data.get('year') else None,
        season=data.get('season') or None,
        category=data.get('category') or None,
        shoot_type=data.get('shootType') or None,
        city_id=data.get('cityId') or None,
        letter=data.get('letter') or None,
    )
    start_page = max(0, int(data.get('startPage', 0)))
    # Five pages is 100 rows: enough to fill the list and a screen of scroll
    # past it, without holding the connection open for a crawl.
    pages = max(1, min(int(data.get('pages', 5)), 25))

    def generate():
        total = 0
        next_page = start_page
        has_more = False
        try:
            window = []
            sent = {}
            for chunk in fv.iter_search_pages(
                start_page=start_page, pages=pages, **filters
            ):
                window.extend(chunk['rows'])
                rows = [_row_to_dict(r) for r in chunk['rows']]
                sent.update({row['collection_id']: row['subtitle'] for row in rows})
                total += len(rows)
                next_page = chunk['page'] + 1
                has_more = not chunk['last']
                yield _sse({
                    'type': 'collections',
                    'collections': rows,
                    'total': total,
                    'page': chunk['page'],
                })

            # Telling near-identical rows apart costs a request each, so it
            # runs once the window is already on screen rather than holding
            # it back. Only rows whose label actually changed are re-sent.
            fv.fill_look_counts(window)
            final = [_row_to_dict(r) for r in window]
            _number_ties(final)
            relabelled = {row['collection_id']: row['subtitle'] for row in final
                          if row['subtitle'] != sent.get(row['collection_id'])}
            if relabelled:
                yield _sse({'type': 'relabel', 'labels': relabelled})

            yield _sse({'type': 'done', 'total': total, 'nextPage': next_page,
                        'hasMore': has_more, 'success': True})
        except Exception as e:
            yield _sse({'type': 'error', 'error': str(e), 'success': False})

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# The designer index, committed alongside the coverage catalog and for the
# same reason: derived data that costs 27 requests to someone else's site and
# only changes when firstVIEW adds a label. Rebuild with
# firstview.build_designer_index(DESIGNERS_PATH).
DESIGNERS_PATH = "backend/high_fashion/designers.json"

# Built once on first request and held: the file is 335 KB of JSON that never
# changes between deploys, and gzipping it per request would be 80 KB of work
# to send the same 80 KB.
_designers_payload = None


def _designer_index_payload():
    """The index as (raw_json, gzipped_json, etag), or None if it is missing."""
    global _designers_payload
    if _designers_payload is None:
        from backend.high_fashion import firstview as fv
        from backend.high_fashion import show_index

        data = fv.load_designer_index(DESIGNERS_PATH)
        if data is None:
            return None

        # Attach how many catalogue entries each designer has. This is the
        # count that used to be impossible without a request per designer —
        # one GROUP BY over the local index answers it for all 8,657 at once.
        #
        # Entries, not distinct runway shows: firstVIEW lists a show once per
        # shoot, so the number includes the Details and Atmosphere sets.
        indexed = 0
        try:
            with db.transaction() as conn:
                if show_index.count(conn) > 0:
                    counts = show_index.designer_counts(
                        conn, [d['name'] for d in data['designers']])
                    for d in data['designers']:
                        n = counts.get(d['name'].lower())
                        if n:
                            d['entries'] = n
                            indexed += 1
        except Exception as exc:  # noqa: BLE001 — counts are a nicety
            print(f"designer counts unavailable: {exc}")

        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        etag = f'W/"designers-{data.get("built_on")}-{data.get("count")}-{indexed}"'
        _designers_payload = (raw, gzip.compress(raw, 6), etag)
    return _designers_payload


def get_designers():
    """GET /api/designers - every designer firstVIEW lists, names and ids.

    Sent whole, once, so the search box can match locally. 8,657 names is
    335 KB raw and about 80 KB gzipped — small enough that holding it in the
    browser beats a request per keystroke, and the only way to get fuzzy
    matching at all: firstVIEW's own search is a plain substring, so a typo
    like "commes" finds nothing.
    """
    payload = _designer_index_payload()
    if payload is None:
        # Absent rather than empty: the search box should say it cannot search
        # rather than silently behave as though the archive had no designers.
        return jsonify({
            'error': 'designer index is not built',
            'success': False,
        }), 503

    raw, gzipped, etag = payload

    if request.headers.get('If-None-Match') == etag:
        return Response(status=304, headers={'ETag': etag})

    accepts_gzip = 'gzip' in (request.headers.get('Accept-Encoding') or '')
    body = gzipped if accepts_gzip else raw
    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'ETag': etag,
        # no-cache means "revalidate", not "do not store": the browser still
        # keeps it and still gets a 304 with no body, but it asks first.
        #
        # max-age=86400 was wrong. The payload changes when the show index is
        # rebuilt — that is what puts the entry counts in it — and a day of
        # not asking meant clients ranking search results by a copy that had
        # no counts at all, which is exactly the bug this caused.
        'Cache-Control': 'no-cache',
    }
    if accepts_gzip:
        headers['Content-Encoding'] = 'gzip'
    return Response(body, headers=headers)


def stream_designer_collections():
    """POST /api/designer/stream - every show by one designer, as they arrive.

    The one view the season filters cannot produce. collection_designer.php
    ignores year, season and gender entirely, so this is a designer's whole
    working life in one list: Yohji Yamamoto is 175 shows over 1995-2027,
    both genders, across nine pages.

    Paged out as it crawls, like /api/catalog/stream, so rows appear at once
    rather than after five seconds.
    """
    from backend.high_fashion import firstview as fv

    data = request.get_json() or {}
    designer_id = str(data.get('designerId') or '').strip()
    if not designer_id:
        return jsonify({'error': 'designerId is required', 'success': False}), 400

    def generate():
        total = 0
        try:
            window = []
            sent = {}
            for chunk in fv.iter_designer_collections(designer_id):
                window.extend(chunk['rows'])
                rows = [_row_to_dict(r) for r in chunk['rows']]
                sent.update({row['collection_id']: row['subtitle'] for row in rows})
                total += len(rows)
                yield _sse({'type': 'collections', 'collections': rows,
                            'total': total, 'page': chunk['page']})

            fv.fill_look_counts(window)
            final = [_row_to_dict(r) for r in window]
            _number_ties(final)
            relabelled = {row['collection_id']: row['subtitle'] for row in final
                          if row['subtitle'] != sent.get(row['collection_id'])}
            if relabelled:
                yield _sse({'type': 'relabel', 'labels': relabelled})

            yield _sse({'type': 'done', 'total': total, 'hasMore': False,
                        'success': True})
        except Exception as e:
            yield _sse({'type': 'error', 'error': str(e), 'success': False})

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def _index_row_to_dict(row):
    """An indexed show, in the shape the list already renders."""
    from backend.high_fashion import firstview as fv

    bits = []
    if row.get('season') and row.get('year'):
        bits.append(f"{_SEASON_SHORT.get(row['season'], row['season'])} {row['year']}")
    elif row.get('year'):
        bits.append(str(row['year']))
    if row.get('gender'):
        bits.append(row['gender'])
    if row.get('category'):
        bits.append(_CATEGORY_SHORT.get(row['category'], row['category']))
    if row.get('shoot_type') and row['shoot_type'] != 'Runway Collection':
        bits.append(_SHOOT_SHORT.get(row['shoot_type'], row['shoot_type']))
    if row.get('city'):
        bits.append(row['city'])

    return {
        'designer': row.get('designer') or '',
        'designer_name': row.get('designer'),
        'subtitle': ' · '.join(bits),
        'url': fv.collection_url(row['collection_id']),
        'collection_id': row['collection_id'],
        'season': row.get('season'),
        'year': row.get('year'),
        'gender': row.get('gender'),
        'category': row.get('category'),
        'shoot_type': row.get('shoot_type'),
        'city': row.get('city'),
        'look_count': None,
        'text': '', 'photos': '', 'date': '',
    }


def _index_available():
    """Whether the local index has anything in it.

    Everything below falls back to crawling firstVIEW when it does not, so a
    database without the index is slow rather than broken.
    """
    try:
        from backend.high_fashion import show_index
        with db.transaction() as conn:
            return show_index.count(conn) > 0
    except Exception as exc:  # noqa: BLE001
        print(f"show index unavailable: {exc}")
        return False


def browse_catalog():
    """POST /api/browse - the archive list, straight from the local index.

    What /api/catalog/stream did by crawling firstVIEW, in one query against
    55,700 rows we already hold: no request to their site, no streaming, and
    a page of results in single-digit milliseconds instead of 1-3 seconds.

    Takes the same filters, plus `text` for a free-text query and `offset`
    for paging. Returns the facet counts alongside, so the filter dropdowns
    can offer exactly what is reachable and nothing that is not.
    """
    from backend.high_fashion import show_index

    data = request.get_json() or {}
    filters = {k: data.get(k) for k in
               ('gender', 'year', 'season', 'category', 'shootType', 'city',
                'designer', 'letter')}
    filters = {k: v for k, v in filters.items() if v not in (None, '')}
    text = (data.get('text') or '').strip()
    limit = max(1, min(int(data.get('limit', 200)), 500))
    offset = max(0, int(data.get('offset', 0)))

    try:
        with db.transaction() as conn:
            result = show_index.query(conn, filters=filters, text=text or None,
                                      limit=limit, offset=offset)
            payload = {
                'collections': [_index_row_to_dict(r) for r in result['rows']],
                'total': result['total'],
                'hasMore': result['hasMore'],
                'offset': offset,
                'success': True,
            }
            if data.get('facets'):
                payload['facets'] = show_index.facets(
                    conn, filters=filters, text=text or None)
            return jsonify(payload)
    except Exception as e:
        import traceback
        print(f"ERROR browse_catalog: {traceback.format_exc()}")
        return jsonify({'error': str(e), 'success': False}), 500


def search_shows():
    """POST /api/search - free text over every show in the archive.

    The thing firstVIEW cannot do: their search covers designer names only,
    so "chanel fw25" had no query to be and would otherwise have to be
    guessed apart into a designer and two filters.

    Here it is one query. Each term must match, and the indexed text carries
    the abbreviations people actually type — fw25, aw2025, rtw, couture — so
    word order does not matter and nothing has to be parsed.

    Returns matching shows and, alongside them, the designers whose names
    match, with exact entry counts.
    """
    from backend.high_fashion import show_index

    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    limit = max(1, min(int(data.get('limit', 60)), 200))

    if not text:
        return jsonify({'shows': [], 'designers': [], 'total': 0, 'success': True})

    try:
        with db.transaction() as conn:
            result = show_index.query(conn, text=text, limit=limit)
            designers = show_index.top_designers(conn, text=text, limit=8)
        return jsonify({
            'shows': [_index_row_to_dict(r) for r in result['rows']],
            'total': result['total'],
            'hasMore': result['hasMore'],
            'designers': designers,
            'success': True,
        })
    except Exception as e:
        import traceback
        print(f"ERROR search_shows: {traceback.format_exc()}")
        return jsonify({'error': str(e), 'success': False}), 500


def get_index_status():
    """GET /api/index/status - how much of the archive is held locally."""
    from backend.high_fashion import show_index

    try:
        with db.transaction() as conn:
            return jsonify({'shows': show_index.count(conn), 'success': True})
    except Exception as e:
        return jsonify({'error': str(e), 'shows': 0, 'success': False}), 500


def refresh_index():
    """POST /api/index/refresh - pick up shows added since the index was built.

    Results are newest first, so this reads from page 0 until it meets ids it
    already has: a new season costs a couple of dozen requests rather than
    the 2,785 a rebuild would.
    """
    from backend.high_fashion import firstview as fv
    from backend.high_fashion import show_index

    try:
        with db.transaction() as conn:
            known = show_index.known_ids(conn)
        fresh = fv.refresh_show_index(known)
        added = 0
        if fresh:
            with db.transaction() as conn:
                added = show_index.upsert(conn, fresh)
        return jsonify({'added': added, 'checked_against': len(known),
                        'success': True})
    except Exception as e:
        import traceback
        print(f"ERROR refresh_index: {traceback.format_exc()}")
        return jsonify({'error': str(e), 'success': False}), 500


def stream_download_images():
    """POST /api/download-images/stream - a show's looks, as they download.

    Emits {type:'meta'} with every look's metadata before any image has
    landed (so the grid can be laid out at once), then {type:'image'} per
    file, then {type:'done'}.
    """
    from backend.high_fashion import firstview as fv

    data = request.get_json() or {}
    collection_url = data.get('collectionUrl', '')
    if not collection_url:
        return jsonify({'error': 'collectionUrl is required', 'success': False}), 400
    quality = data.get('quality', fv.QUALITY_FULL)
    designer_hint = data.get('designerName')
    collection_id = fv.collection_id_from_url(collection_url) or collection_url

    # A stored show replays instantly: the same meta/image/done events, but
    # read out of R2 rather than fetched from firstVIEW. Done before the
    # generator so a hit does not open a temp directory it will not use.
    cached = _cache_lookup(collection_id, quality)
    if cached:
        _record_recent(collection_id, cached, cached['images'])

        def replay():
            yield _sse({
                'type': 'meta',
                'designer': cached.get('designer'),
                'season': cached.get('season'),
                'gender': cached.get('gender'),
                'category': cached.get('category'),
                'collection_id': collection_id,
                'count': len(cached['images']),
                'cached': True,
                'looks': [],
            })
            for img in sorted(cached['images'], key=lambda i: i.get('index', 0)):
                yield _sse({'type': 'image', **img})
            yield _sse({
                'type': 'done',
                'count': len(cached['images']),
                'failed': [],
                'designer': cached.get('designer'),
                'season': cached.get('season'),
                'success': True,
                'cached': True,
            })

        return Response(replay(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache',
                                 'X-Accel-Buffering': 'no'})

    def generate():
        # Same store-and-temp-dir contract as download_images: each look is
        # uploaded as it lands and the event carries a URL, never a path on
        # this machine. The temp directory goes away in the finally.
        #
        # Uploads run in a pool rather than one after another. Fetching a look
        # from firstVIEW takes ~0.026s; storing it in R2 takes ~0.47s, so a
        # serial upload per look *was* the download — 89 looks took 44.6s, of
        # which 41.6s was this one step waiting on R2. The fetch was never the
        # slow part, and hurrying firstVIEW would have bought almost nothing.
        store = images.get_store()
        temp_dir = tempfile.mkdtemp(prefix='runway_')
        designer = designer_hint or 'unknown'
        uploaded_all = []
        pending = []
        done_payload = None

        def deliver(futures):
            """Emit an SSE frame for each finished upload in `futures`."""
            for fut in futures:
                up = fut.result()          # _upload_one swallows its own errors
                if up is None:
                    continue
                uploaded_all.append(up)
                yield _sse({'type': 'image', **up})

        try:
            with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
                for kind, payload in fv.iter_download_collection(
                    collection_url, out_root=temp_dir, quality=quality
                ):
                    if kind == 'meta':
                        designer = designer_hint or payload.get('designer') or 'unknown'
                        payload = {k: v for k, v in payload.items() if k != 'cache_dir'}
                        yield _sse({'type': 'meta', **payload})

                    elif kind == 'image':
                        pending.append(pool.submit(_upload_one, store, designer, {
                            'local_path': payload['path'],
                            'source_url': payload['url'],
                            'index': payload['index'],
                            'filename': payload['filename'],
                        }))
                        # Hand back whatever has already landed without
                        # blocking on the rest, so looks keep appearing while
                        # later ones are still uploading.
                        ready = [f for f in pending if f.done()]
                        pending = [f for f in pending if not f.done()]
                        yield from deliver(ready)

                    elif kind == 'error':
                        # One look that would not download. Named apart from a
                        # stream error: the client aborts the whole show on
                        # `error`, so a single missing image used to end the
                        # download of every image after it.
                        yield _sse({'type': 'image_error', **payload})

                    elif kind == 'done':
                        done_payload = payload

                # Every look has been fetched; wait out the uploads still going.
                yield from deliver(as_completed(pending))

            if done_payload is not None:
                # `images` in done_payload still hold local paths; the client
                # has already received each one as a URL above. Store the
                # uploaded set so the next open skips firstVIEW entirely.
                uploaded_all.sort(key=lambda i: i.get('index', 0))
                _cache_store(collection_id, quality, uploaded_all,
                             {**done_payload, 'designer': designer}, store)
                _record_recent(collection_id,
                               {**done_payload, 'designer': designer},
                               uploaded_all)
                done_payload = {k: v for k, v in done_payload.items()
                                if k not in ('images', 'cache_dir')}
                yield _sse({'type': 'done', **done_payload,
                            'count': len(uploaded_all)})
        except Exception as e:
            import traceback
            print(f"ERROR stream_download_images: {traceback.format_exc()}")
            yield _sse({'type': 'error', 'error': str(e), 'success': False})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def download_video():
    """POST /api/download-video - find this show's runway video on YouTube.

    Cache first, always. A search costs 100 of the day's 10,000 quota units,
    so it is only ever spent on a (designer, season, gender) nobody has
    looked up before. Hits and misses are both remembered: a designer with
    no runway video would otherwise cost 100 units on every click.
    """
    try:
        from backend.high_fashion import video_search as vs
        from backend.high_fashion.tools.claude_video_verifier import ClaudeVideoVerifier

        data = request.get_json() or {}
        designer_name = (data.get('designerName') or '').strip()
        season_name = (data.get('seasonName') or '').strip()
        gender = (data.get('gender') or '').strip()

        if not designer_name:
            return jsonify({'error': 'designerName is required', 'success': False}), 400

        key = vs.query_key(designer_name, season_name, gender)
        query_text = vs.build_query(designer_name, season_name, gender)

        with db.transaction() as conn:
            hit = vs.cached(conn, key)

        if hit is not None:
            if not hit['found']:
                return jsonify({'success': False, 'cached': True,
                                'error': 'No runway video found for this show'})
            return jsonify({
                'success': True,
                'videoId': hit['video_id'],
                'youtubeUrl': hit['youtube_url'],
                'embedUrl': hit['embed_url'],
                'title': hit['title'],
                'thumbnail': hit['thumbnail'],
                'cached': True,
            })

        # Never looked up: this is the request that costs quota.
        try:
            with db.transaction() as conn:
                candidates = vs.search(conn, query_text)
        except vs.QuotaExhausted as exc:
            return jsonify({'success': False, 'error': str(exc),
                            'quotaExhausted': True}), 429
        except RuntimeError as exc:          # no API key configured
            return jsonify({'success': False, 'error': str(exc),
                            'notConfigured': True}), 503

        chosen = None
        if candidates:
            # The verifier holds the fashion logic — Couture vs Haute
            # Couture, 2010 meaning a 2010-11 show. Prefer its judgement; if
            # it cannot run, the top result beats nothing, since the query
            # was already specific.
            try:
                verdict = ClaudeVideoVerifier().verify_video_matches(query_text, candidates)
                if not getattr(verdict, 'available', True):
                    # The verifier could not run. That is not the same as "no
                    # video matched" — reading it that way is what made every
                    # lookup fail while a retired model id went unnoticed.
                    print(f"video verifier unavailable ({verdict.reasoning}); "
                          f"taking top result")
                    chosen = candidates[0]
                elif verdict.is_match:
                    idx = verdict.best_match_index
                    chosen = candidates[idx] if idx is not None else candidates[0]
            except Exception as exc:  # noqa: BLE001
                print(f"video verifier raised, taking top result: {exc}")
                chosen = candidates[0]

        result = None
        if chosen is not None:
            result = {
                'video_id': chosen.video_id,
                'title': chosen.title,
                'thumbnail': chosen.thumbnail_url,
                'youtube_url': chosen.url,
            }

        with db.transaction() as conn:
            vs.remember(conn, key, query_text, result)

        if result is None:
            return jsonify({'success': False, 'cached': False,
                            'error': 'No runway video found for this show'})

        return jsonify({
            'success': True,
            'videoId': result['video_id'],
            'youtubeUrl': result['youtube_url'],
            'embedUrl': f"https://www.youtube.com/embed/{result['video_id']}",
            'title': result['title'],
            'thumbnail': result['thumbnail'],
            'cached': False,
        })

    except Exception as e:
        import traceback
        print(f"ERROR download_video: {traceback.format_exc()}")
        return jsonify({'error': str(e), 'success': False}), 500


def get_video_quota():
    """GET /api/video/quota - how much YouTube allowance is left today."""
    try:
        from backend.high_fashion import video_search as vs
        with db.transaction() as conn:
            return jsonify({'quota': vs.quota_status(conn), 'success': True})
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500


def serve_fashion_video():
    """GET /api/video?path={path} - Serve cached video"""
    try:
        video_path = request.args.get('path', '')

        if not video_path or not os.path.exists(video_path):
            return jsonify({'error': 'Video not found'}), 404

        return send_file(video_path, mimetype='video/mp4')

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def cleanup_fashion_cache():
    """POST /api/cleanup - Clear locally downloaded images.

    Only the images directory is removed, not the whole of
    backend/high_fashion/cache. Development-only in practice: production
    downloads into a temp directory and uploads to the image store, so
    there is nothing here to clear.
    """
    try:
        images_dir = Path("backend/high_fashion/cache/images")
        if images_dir.exists():
            shutil.rmtree(images_dir)
            images_dir.mkdir(parents=True, exist_ok=True)

        return jsonify({
            'success': True,
            'message': 'Downloaded images cleared'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_recents():
    """GET /api/recents - shows the signed-in user has opened, newest first."""
    try:
        with db.transaction() as conn:
            return jsonify({
                'recents': recents.list_recent(conn, user_id=current_user().id),
                'success': True,
            })
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500


def clear_recents():
    """DELETE /api/recents - forget the current user's history."""
    try:
        with db.transaction() as conn:
            removed = recents.clear(conn, user_id=current_user().id)
        return jsonify({'removed': removed, 'success': True})
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500


def get_cache_stats():
    """GET /api/cache/stats - how full the shared show cache is."""
    try:
        with db.transaction() as conn:
            return jsonify({'cache': collection_cache.stats(conn), 'success': True})
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500


def register_high_fashion_routes(app):
    """Register all high fashion routes"""

    app.add_url_rule('/api/seasons', 'get_seasons', get_seasons, methods=['POST'])
    app.add_url_rule('/api/collections', 'get_collections', get_collections, methods=['POST'])
    app.add_url_rule('/api/download-images', 'download_images', download_images, methods=['POST'])
    app.add_url_rule('/api/recents', 'get_recents', get_recents, methods=['GET'])
    app.add_url_rule('/api/recents', 'clear_recents', clear_recents, methods=['DELETE'])
    app.add_url_rule('/api/cache/stats', 'get_cache_stats', get_cache_stats, methods=['GET'])
    app.add_url_rule('/api/video/quota', 'get_video_quota', get_video_quota, methods=['GET'])
    app.add_url_rule('/api/collections/stream', 'stream_collections_sse', stream_collections, methods=['POST'])
    app.add_url_rule('/api/catalog/stream', 'stream_catalog_sse', stream_catalog, methods=['POST'])
    app.add_url_rule('/api/designers', 'get_designers', get_designers, methods=['GET'])
    app.add_url_rule('/api/designer/stream', 'stream_designer_sse', stream_designer_collections, methods=['POST'])
    app.add_url_rule('/api/browse', 'browse_catalog', browse_catalog, methods=['POST'])
    app.add_url_rule('/api/search', 'search_shows', search_shows, methods=['POST'])
    app.add_url_rule('/api/index/status', 'get_index_status', get_index_status, methods=['GET'])
    app.add_url_rule('/api/index/refresh', 'refresh_index', refresh_index, methods=['POST'])
    app.add_url_rule('/api/download-images/stream', 'stream_download_images', stream_download_images, methods=['POST'])
    app.add_url_rule('/api/download-video', 'download_video_fashion', download_video, methods=['POST'])
    app.add_url_rule('/api/images/<path:key>', 'serve_stored_image', serve_stored_image, methods=['GET'])
    app.add_url_rule('/api/video', 'serve_fashion_video', serve_fashion_video, methods=['GET'])
    app.add_url_rule('/api/cleanup', 'cleanup_fashion_cache', cleanup_fashion_cache, methods=['POST'])

    print("✅ High Fashion API routes registered (20 endpoints)")
