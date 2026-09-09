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

import shutil
import tempfile

from backend.storage import images
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


def _row_to_dict(r):
    """One results row, with a label that distinguishes near-identical shows.

    A designer often appears several times in one season. The row itself
    carries category / shoot type / city, and where even those match,
    `look_count` has been filled in to break the tie — so the list never
    shows the same name twice with nothing to tell them apart.
    """
    name = r.designer or r.title
    bits = []
    if r.category and r.category != 'Ready-to-Wear':
        bits.append(r.category)
    if r.shoot_type and r.shoot_type != 'Runway Collection':
        bits.append(r.shoot_type)
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

        uploaded.append({
            # A URL now, not a filesystem path. It used to be an absolute path
            # the client handed back to /api/image?path= for the server to read
            # off disk — meaningless on another machine, and that endpoint read
            # whatever path it was given.
            'path': store.save(images.runway_key(designer_name, entry['filename']), data),
            'source_url': entry['source_url'],
            'index': entry['index'],
            'filename': entry['filename'],
            'success': True,
        })
    return uploaded


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

        return jsonify({
            'success': bool(uploaded),
            'images': uploaded,
            'count': len(uploaded),
            'failed': result.get('failed', []),
            'designer': result.get('designer'),
            'season': result.get('season'),
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

    def generate():
        # Same store-and-temp-dir contract as download_images: each look is
        # uploaded as it lands and the event carries a URL, never a path on
        # this machine. The temp directory goes away in the finally.
        store = images.get_store()
        temp_dir = tempfile.mkdtemp(prefix='runway_')
        designer = designer_hint or 'unknown'
        try:
            for kind, payload in fv.iter_download_collection(
                collection_url, out_root=temp_dir, quality=quality
            ):
                if kind == 'meta':
                    designer = designer_hint or payload.get('designer') or 'unknown'
                    payload = {k: v for k, v in payload.items() if k != 'cache_dir'}
                elif kind == 'image':
                    entry = {
                        'local_path': payload['path'],
                        'source_url': payload['url'],
                        'index': payload['index'],
                        'filename': payload['filename'],
                    }
                    uploaded = _upload_images(store, designer, [entry])
                    if not uploaded:
                        continue
                    payload = uploaded[0]
                elif kind == 'done':
                    # `images` here still hold local paths; the client has
                    # already received each one as a URL above.
                    payload = {k: v for k, v in payload.items()
                               if k not in ('images', 'cache_dir')}
                yield _sse({'type': kind, **payload})
        except Exception as e:
            import traceback
            print(f"ERROR stream_download_images: {traceback.format_exc()}")
            yield _sse({'type': 'error', 'error': str(e), 'success': False})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def download_video():
    """POST /api/download-video - Search for and return a fashion show video"""
    try:
        data = request.get_json()
        designer_name = data.get('designerName', '')
        season_name = data.get('seasonName', '')

        if not designer_name or not season_name:
            return jsonify({'error': 'designerName and seasonName are required'}), 400

        # Build search query from designer + season (e.g. "Givenchy Ready To Wear Fall Winter 2014 Paris")
        search_query = f"{designer_name} {season_name} full fashion show runway"
        print(f"🔍 Video search query: {search_query}")

        # Use EnhancedFashionVideoSearch to find a YouTube video
        import sys
        tools_dir = str(Path(__file__).parent.parent / "high_fashion" / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)

        from claude_video_verifier import EnhancedFashionVideoSearch

        search = EnhancedFashionVideoSearch()
        video_info = search.get_streaming_url(search_query)

        if not video_info:
            return jsonify({'success': False, 'error': 'No matching video found'})

        return jsonify({
            'success': True,
            'videoId': video_info['video_id'],
            'youtubeUrl': video_info['youtube_url'],
            'embedUrl': video_info['embed_url'],
            'title': video_info['title'],
            'thumbnail': video_info['thumbnail']
        })

    except Exception as e:
        import traceback
        print(f"ERROR download_video: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


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


def register_high_fashion_routes(app):
    """Register all high fashion routes"""

    app.add_url_rule('/api/seasons', 'get_seasons', get_seasons, methods=['POST'])
    app.add_url_rule('/api/collections', 'get_collections', get_collections, methods=['POST'])
    app.add_url_rule('/api/download-images', 'download_images', download_images, methods=['POST'])
    app.add_url_rule('/api/collections/stream', 'stream_collections_sse', stream_collections, methods=['POST'])
    app.add_url_rule('/api/download-images/stream', 'stream_download_images', stream_download_images, methods=['POST'])
    app.add_url_rule('/api/download-video', 'download_video_fashion', download_video, methods=['POST'])
    app.add_url_rule('/api/images/<path:key>', 'serve_stored_image', serve_stored_image, methods=['GET'])
    app.add_url_rule('/api/video', 'serve_fashion_video', serve_fashion_video, methods=['GET'])
    app.add_url_rule('/api/cleanup', 'cleanup_fashion_cache', cleanup_fashion_cache, methods=['POST'])

    print("✅ High Fashion API routes registered (9 endpoints)")
