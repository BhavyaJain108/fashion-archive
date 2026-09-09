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

CACHE_ROOT = "backend/high_fashion/cache/images"
# Which year/season/gender/category combinations actually have shows.
# Built by firstview.build_coverage; absent until then, in which case every
# option stays selectable.
COVERAGE_PATH = "backend/high_fashion/cache/coverage.json"


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


def download_images():
    """POST /api/download-images - Download every look in one show.

    `collectionUrl` is a collection_images.php URL (or a bare id). Returns
    the same {images, count, cache_dir} shape as before; each image entry
    keeps path/url/index/filename.
    """
    try:
        from backend.high_fashion import firstview as fv

        data = request.get_json() or {}
        collection_url = data.get('collectionUrl', '')
        if not collection_url:
            return jsonify({'error': 'collectionUrl is required', 'success': False}), 400

        quality = data.get('quality', fv.QUALITY_FULL)
        result = fv.download_collection(
            collection_url,
            out_root=CACHE_ROOT,
            quality=quality,
        )
        return jsonify(result)

    except Exception as e:
        import traceback
        print(f"ERROR download_images: {traceback.format_exc()}")
        return jsonify({'error': str(e), 'success': False}), 500


def serve_fashion_image():
    """GET /api/image?path={path} - Serve cached fashion image"""
    try:
        image_path = request.args.get('path', '')
        print(f"DEBUG serve_image: Requested path: {image_path}")

        if not image_path:
            return jsonify({'error': 'No path provided'}), 400

        # Convert to absolute path if relative
        # The working directory when running backend/app.py is the project root
        if not os.path.isabs(image_path):
            # Get project root (parent of backend directory)
            project_root = Path(__file__).parent.parent.parent
            absolute_path = project_root / image_path
        else:
            absolute_path = Path(image_path)

        print(f"DEBUG serve_image: Absolute path: {absolute_path}")
        print(f"DEBUG serve_image: Path exists: {absolute_path.exists()}")

        if not absolute_path.exists():
            print(f"DEBUG serve_image: File not found at {absolute_path}")
            return jsonify({'error': 'Image not found', 'path': str(absolute_path)}), 404

        print(f"DEBUG serve_image: Serving file: {absolute_path}")
        return send_file(str(absolute_path))

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR serve_image: {error_details}")
        return jsonify({'error': str(e), 'traceback': error_details}), 500


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

    def generate():
        try:
            for kind, payload in fv.iter_download_collection(
                collection_url, out_root=CACHE_ROOT, quality=quality
            ):
                yield _sse({'type': kind, **payload})
        except Exception as e:
            import traceback
            print(f"ERROR stream_download_images: {traceback.format_exc()}")
            yield _sse({'type': 'error', 'error': str(e), 'success': False})

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
    """POST /api/cleanup - Clear cache directories"""
    try:
        import shutil

        cache_dir = Path("backend/high_fashion/cache")
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)

        return jsonify({
            'success': True,
            'message': 'Cache cleared successfully'
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
    app.add_url_rule('/api/image', 'serve_fashion_image', serve_fashion_image, methods=['GET'])
    app.add_url_rule('/api/video', 'serve_fashion_video', serve_fashion_video, methods=['GET'])
    app.add_url_rule('/api/cleanup', 'cleanup_fashion_cache', cleanup_fashion_cache, methods=['POST'])

    print("✅ High Fashion API routes registered (9 endpoints)")
