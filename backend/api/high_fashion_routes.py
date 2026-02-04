"""
High Fashion API Routes
========================

Endpoints for nowfashion.com scraping:
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

# Headers for nowfashion.com
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

BASE_URL = "https://nowfashion.com"
SEASONS_URL = "https://nowfashion.com/fashion-week-seasons/"


def get_seasons():
    """GET /api/seasons - List all fashion seasons"""
    try:
        response = requests.get(SEASONS_URL, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        links = soup.find_all('a', href=True)
        season_links = []

        for link in links:
            href = link.get('href')
            text = link.get_text().strip()

            if href and '/fashion/collections/' in href:
                full_url = urljoin(BASE_URL, href)
                if text and len(text) > 5:
                    season_links.append((text, full_url))

        # Remove duplicates and sort
        season_links = list(set(season_links))
        season_links.sort(key=lambda x: x[0])

        seasons = []
        for text, url in season_links:
            seasons.append({
                'name': text,
                'url': url,
                'href': url.replace(BASE_URL, '')
            })

        return jsonify({'seasons': seasons, 'success': True})

    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500


def get_collections():
    """POST /api/collections - Get collections for a season"""
    try:
        data = request.get_json()
        season_url = data.get('seasonUrl', '')

        collections = []
        page = 1

        while True:
            if page == 1:
                current_url = season_url
            else:
                current_url = f"{season_url.rstrip('/')}/page/{page}/"

            response = requests.get(current_url, headers=HEADERS, timeout=10)

            if response.status_code == 404:
                break

            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            h2_elements = soup.find_all('h2', class_='wp-block-post-title')

            if not h2_elements:
                break

            page_collections = []
            for h2 in h2_elements:
                link = h2.find('a', href=True)
                if link:
                    href = link.get('href')
                    designer_text = link.get_text().strip()

                    if href and designer_text:
                        page_collections.append({
                            'designer': designer_text,
                            'photos': '',
                            'date': '',
                            'url': href,
                            'text': designer_text
                        })

            if not page_collections:
                break

            collections.extend(page_collections)

            # Check pagination
            has_next_page = False
            next_link = soup.find('a', string=re.compile(r'next|Next', re.IGNORECASE))
            if next_link or len(page_collections) > 0:
                has_next_page = True

            if not has_next_page:
                break

            page += 1
            if page > 10:  # Safety limit
                break

        # Remove duplicates and sort alphabetically
        unique_collections = []
        seen_designers = set()

        for collection in collections:
            designer_key = collection['designer'].lower().strip()
            if designer_key not in seen_designers:
                seen_designers.add(designer_key)
                unique_collections.append(collection)

        unique_collections.sort(key=lambda x: x['designer'].lower())

        return jsonify({'collections': unique_collections, 'success': True})

    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500


def download_images():
    """POST /api/download-images - Download images from a collection with parallel downloads and filtering"""
    try:
        data = request.get_json()
        collection_url = data.get('collectionUrl', '')
        designer_name = data.get('designerName', '')

        print(f"DEBUG: download_images called with URL: {collection_url}, Designer: {designer_name}")

        # Create cache directory
        cache_dir = Path("backend/high_fashion/cache/images") / designer_name.replace(' ', '_').replace('/', '_')
        cache_dir.mkdir(parents=True, exist_ok=True)
        print(f"DEBUG: Cache dir created: {cache_dir}")

        # Extract collection name from URL for filtering
        parsed_url = urlparse(collection_url)
        collection_name = parsed_url.path.strip('/').split('/')[-1]
        print(f"DEBUG: Collection name from URL: {collection_name}")

        response = requests.get(collection_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        print(f"DEBUG: Fetched page, status: {response.status_code}")

        # Find all image tags
        img_tags = soup.find_all('img')
        print(f"DEBUG: Found {len(img_tags)} img tags")
        image_urls = []

        for img in img_tags:
            src = img.get('src') or img.get('data-src')
            if src and ('nowfashion.com' in src or src.startswith('/')):
                if src.startswith('/'):
                    src = urljoin(BASE_URL, src)
                if src not in image_urls:
                    image_urls.append(src)

        print(f"DEBUG: Extracted {len(image_urls)} unique image URLs")

        # PARALLEL DOWNLOADING using ThreadPoolExecutor
        downloaded_images = []
        download_lock = Lock()
        num_threads = min(len(image_urls), 20)  # Up to 20 parallel downloads

        print(f"DEBUG: Starting parallel download with {num_threads} threads")

        def download_single_image(idx, img_url):
            """Download a single image (used in parallel)"""
            try:
                img_response = requests.get(img_url, headers=HEADERS, timeout=15)
                img_response.raise_for_status()

                # Preserve original filename from URL
                from urllib.parse import urlparse, unquote
                parsed = urlparse(img_url)
                original_filename = unquote(os.path.basename(parsed.path))

                # If no filename or it's generic, fall back to URL-based name
                if not original_filename or original_filename in ['', 'image', 'img']:
                    original_filename = f"image_{idx+1:03d}.jpg"

                # Clean filename (remove invalid characters)
                filename = re.sub(r'[^\w\-_\.]', '_', original_filename)

                filepath = cache_dir / filename

                with open(filepath, 'wb') as f:
                    f.write(img_response.content)

                return {
                    'path': str(filepath.absolute()),
                    'url': img_url,
                    'index': idx,
                    'filename': filename,
                    'success': True
                }

            except Exception as e:
                print(f"Failed to download {img_url}: {e}")
                return {'success': False, 'url': img_url, 'error': str(e)}

        # Download images in parallel
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            # Submit all download tasks
            future_to_idx = {
                executor.submit(download_single_image, idx, url): idx
                for idx, url in enumerate(image_urls)
            }

            # Collect results as they complete
            for future in as_completed(future_to_idx):
                result = future.result()
                if result.get('success'):
                    with download_lock:
                        downloaded_images.append(result)
                        print(f"Downloaded ({len(downloaded_images)}/{len(image_urls)}): {result['filename']}")

        print(f"DEBUG: Downloaded {len(downloaded_images)} images, now applying collection organizer filter...")

        # APPLY COLLECTION ORGANIZER FILTERING
        try:
            from backend.high_fashion.collection_organizer import CollectionOrganizer

            organizer = CollectionOrganizer(str(cache_dir))
            result = organizer.organize_folder_with_url_info(collection_name, dry_run=False)

            if 'error' not in result:
                print(f"DEBUG: Organizer kept {result['keeping_files']} files, removed {result['removing_files']} files")

                # Rebuild the downloaded_images list to only include kept files
                kept_filenames = set()
                for file in organizer.scan_folder():
                    # Exclude the removed_files directory
                    if 'removed_files' not in str(file):
                        kept_filenames.add(file)

                filtered_images = [img for img in downloaded_images if Path(img['path']).name in kept_filenames]

                # Sort images by look number extracted from filename (e.g., -0001, -0002)
                def extract_look_number(img):
                    filename = Path(img['path']).name
                    match = re.search(r'-(\d+)\.', filename)
                    return int(match.group(1)) if match else 0

                filtered_images.sort(key=extract_look_number)
                print(f"DEBUG: After filtering: {len(filtered_images)} images remain, sorted by look number")

                return jsonify({
                    'success': True,
                    'images': filtered_images,
                    'count': len(filtered_images),
                    'cache_dir': str(cache_dir),
                    'filtering_applied': True,
                    'removed_count': result['removing_files']
                })
            else:
                print(f"DEBUG: Organizer returned error: {result['error']}, returning all downloaded images")

        except Exception as e:
            print(f"DEBUG: Collection organizer failed: {e}, returning all downloaded images")

        # If filtering fails, return all downloaded images (still sort them!)
        def extract_look_number(img):
            filename = Path(img['path']).name
            match = re.search(r'-(\d+)\.', filename)
            return int(match.group(1)) if match else 0

        downloaded_images.sort(key=extract_look_number)

        return jsonify({
            'success': True,
            'images': downloaded_images,
            'count': len(downloaded_images),
            'cache_dir': str(cache_dir),
            'filtering_applied': False
        })

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR in download_images: {error_details}")
        return jsonify({'error': str(e), 'traceback': error_details, 'success': False}), 500


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
            return jsonify({'error': 'No matching video found'}), 404

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
    app.add_url_rule('/api/download-video', 'download_video_fashion', download_video, methods=['POST'])
    app.add_url_rule('/api/image', 'serve_fashion_image', serve_fashion_image, methods=['GET'])
    app.add_url_rule('/api/video', 'serve_fashion_video', serve_fashion_video, methods=['GET'])
    app.add_url_rule('/api/cleanup', 'cleanup_fashion_cache', cleanup_fashion_cache, methods=['POST'])

    print("✅ High Fashion API routes registered (7 endpoints)")
