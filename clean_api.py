#!/usr/bin/env python3
"""
Clean API Backend - NO tkinter dependencies
Pure scraping functions extracted from the working code
"""

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import os
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

app = Flask(__name__)
CORS(app)

# EXACT headers from working version
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

base_url = "https://nowfashion.com"
seasons_url = "https://nowfashion.com/fashion-week-seasons/"

@app.route('/api/seasons', methods=['POST'])
def get_seasons():
    """Pure season scraping - NO tkinter"""
    try:
        response = requests.get(seasons_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # EXACT logic from working version
        links = soup.find_all('a', href=True)
        season_links = []
        
        for link in links:
            href = link.get('href')
            text = link.get_text().strip()
            
            if href and '/fashion/collections/' in href:
                full_url = urljoin(base_url, href)
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
                'href': url.replace(base_url, '')
            })
        
        return jsonify({'seasons': seasons, 'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/collections', methods=['POST'])
def get_collections():
    """Pure collection scraping - NO tkinter"""
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
            
            response = requests.get(current_url, headers=headers, timeout=10)
            
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
            
            # Check pagination - simplified
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

@app.route('/api/download-images', methods=['POST'])
def download_images():
    """Use original ImageDownloader - NO tkinter imports"""
    try:
        import sys
        import os
        sys.path.append(os.path.dirname(__file__))
        
        # Import ONLY the classes we need
        from image_downloader import ImageDownloader, DownloadConfig
        
        data = request.get_json()
        collection = data.get('collection', {})
        
        config = DownloadConfig(
            url=collection['url'],
            output_dir='downloads',
            max_images=50,
            delay=1.0,
            timeout=30,
            retries=3,
            user_agent=headers['User-Agent']
        )
        
        downloader = ImageDownloader(config)
        downloaded_files = downloader.download_all()
        
        # Run organization on downloaded files (EXACT copy from original)
        if downloaded_files:
            try:
                from collection_organizer import CollectionOrganizer
                
                # Extract collection info from URL
                url_parts = collection['url'].strip('/').split('/')
                collection_name = url_parts[-1] if url_parts else ""
                
                # Use URL-based organization
                organizer = CollectionOrganizer(config.output_dir)
                result = organizer.organize_folder_with_url_info(collection_name, dry_run=False)
                print(f"Organization result: {result}")
            except Exception as e:
                print(f"Organization error: {e}")
        
        # Apply EXACT filtering logic from original load_downloaded_images method
        final_images = []
        if downloaded_files:
            from pathlib import Path
            import re
            
            # Filter to only existing files (post-organization)
            existing_images = [path for path in downloaded_files if Path(path).exists()]
            print(f"Found {len(existing_images)} existing image files after organization")
            
            # Also check what's actually in the downloads folder
            downloads_path = Path("downloads")
            if downloads_path.exists():
                actual_files = list(downloads_path.glob("*"))
                print(f"Files actually in downloads folder: {len(actual_files)}")
                # Use actual files from downloads folder instead
                existing_images = [str(f) for f in actual_files if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.webp']]
                print(f"Found {len(existing_images)} image files in downloads folder")
            
            if existing_images:
                # Validate images using second image as reference (if available) - EXACT logic from original
                if len(existing_images) >= 2:
                    second_image = Path(existing_images[1]).name
                    print(f"Using second image as reference: {second_image}")
                    
                    # Extract pattern from second image: remove numbers from end
                    pattern_match = re.match(r'^(.+?)-\d+\.[^.]+$', second_image)
                    if pattern_match:
                        core_pattern = pattern_match.group(1)
                        print(f"Extracted pattern: '{core_pattern}'")
                        
                        # Filter images that contain this pattern
                        valid_images = []
                        for img_path in existing_images:
                            img_name = Path(img_path).name
                            if core_pattern.lower() in img_name.lower():
                                valid_images.append(img_path)
                            else:
                                print(f"Excluding {img_name} - doesn't match pattern")
                        
                        if valid_images:
                            existing_images = valid_images
                            print(f"Validated {len(valid_images)} images match the pattern")
                        else:
                            print("No images matched pattern, keeping all")
                    else:
                        print("Could not extract pattern from second image")
                
                # Sort images by look number - EXACT logic from original
                def extract_look_number(image_path):
                    filename = Path(image_path).name
                    look_match = re.search(r'-(\d+)\.[^.]+$', filename)
                    return int(look_match.group(1)) if look_match else 0
                
                existing_images.sort(key=extract_look_number)
                print(f"Sorted {len(existing_images)} images by look number")
                
                final_images = existing_images
        
        return jsonify({
            'success': True,
            'imagePaths': final_images,
            'designerName': collection['designer'],
            'count': len(final_images)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'imagePaths': [],
            'designerName': collection.get('designer', 'Unknown'),
            'error': str(e)
        }), 500

@app.route('/api/download-video', methods=['POST'])
def download_video():
    """Video download without tkinter"""
    try:
        # Only import if available
        try:
            from claude_video_verifier import EnhancedFashionVideoSearch
            video_search_engine = EnhancedFashionVideoSearch()
        except ImportError:
            return jsonify({'videoPath': None, 'success': True})
        
        data = request.get_json()
        collection = data.get('collection', {})
        
        collection_name = f"{collection.get('designer', '')} {collection.get('season', '')} {collection.get('year', '')}"
        video_path = video_search_engine.search_verify_and_download(collection_name)
        
        return jsonify({'videoPath': video_path, 'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/image')
def serve_image():
    try:
        image_path = request.args.get('path', '')
        if not image_path or not os.path.exists(image_path):
            return jsonify({'error': 'Image not found'}), 404
        return send_file(image_path)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup', methods=['POST'])
def cleanup_downloads():
    """Clean up previous downloads (matches tkinter cleanup_previous_downloads)"""
    try:
        import shutil
        from pathlib import Path
        
        downloads_path = Path("downloads")
        if downloads_path.exists():
            # Remove all files in downloads directory
            for item in downloads_path.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            print(f"Cleaned downloads folder")
        
        # Also clean videos folder (matches tkinter clear_videos_folder)
        videos_path = Path("videos")
        if videos_path.exists():
            for item in videos_path.iterdir():
                if item.is_file():
                    item.unlink()
            print(f"Cleaned videos folder")
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"Cleanup error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/collections-stream', methods=['POST'])
def get_collections_stream():
    """Stream collections as they load (matches tkinter stream_collections_update)"""
    try:
        from flask import Response
        import json
        import time
        
        data = request.get_json()
        season_url = data.get('seasonUrl', '')
        
        def generate_collections():
            collections = []
            page = 1
            
            while True:
                if page == 1:
                    current_url = season_url
                else:
                    current_url = f"{season_url.rstrip('/')}/page/{page}/"
                
                try:
                    response = requests.get(current_url, headers=headers, timeout=10)
                    
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
                    
                    # Stream update (matches tkinter streaming)
                    stream_data = {
                        'page': page,
                        'total_collections': len(collections),
                        'page_collections': page_collections,
                        'complete': False
                    }
                    yield f"data: {json.dumps(stream_data)}\n\n"
                    time.sleep(0.1)  # Small delay to show streaming
                    
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
                
                except Exception as e:
                    error_data = {'error': str(e), 'complete': True}
                    yield f"data: {json.dumps(error_data)}\n\n"
                    return
            
            # Remove duplicates and sort (matches tkinter logic)
            unique_collections = []
            seen_designers = set()
            
            for collection in collections:
                designer_key = collection['designer'].lower().strip()
                if designer_key not in seen_designers:
                    seen_designers.add(designer_key)
                    unique_collections.append(collection)
            
            unique_collections.sort(key=lambda x: x['designer'].lower())
            
            # Final complete data
            final_data = {
                'collections': unique_collections,
                'complete': True,
                'total': len(unique_collections)
            }
            yield f"data: {json.dumps(final_data)}\n\n"
        
        return Response(generate_collections(), mimetype='text/event-stream')
    
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/video-test', methods=['POST'])
def video_search_test():
    """Video search test functionality (matches tkinter open_video_test)"""
    try:
        # Only import if available (matches tkinter conditional import)
        try:
            from claude_video_verifier import EnhancedFashionVideoSearch
            video_search_engine = EnhancedFashionVideoSearch()
            
            data = request.get_json()
            search_query = data.get('query', '')
            
            # Test search without downloading
            results = video_search_engine.search_only(search_query)
            
            return jsonify({
                'success': True,
                'results': results,
                'query': search_query
            })
        except ImportError:
            return jsonify({
                'success': False,
                'error': 'Video search functionality not available'
            })
    
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/about', methods=['GET'])
def get_about_info():
    """Get application info (matches tkinter show_about)"""
    return jsonify({
        'name': 'Fashion Week Archive Browser',
        'version': '2.0 - React Edition',
        'description': 'Browse and archive fashion week collections with early Mac styling',
        'original': 'Migrated from tkinter while preserving all functionality',
        'features': [
            'Season and collection browsing',
            'Image downloading and organization', 
            'Gallery and single view modes',
            'Video integration with Claude AI',
            '3-level magnification system',
            'Keyboard navigation',
            'Real-time streaming updates'
        ]
    })

@app.route('/api/video')
def serve_video():
    try:
        video_path = request.args.get('path', '')
        if not video_path or not os.path.exists(video_path):
            return jsonify({'error': 'Video not found'}), 404
        return send_file(video_path)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🎭 Clean API Backend - NO tkinter dependencies")
    print("🔗 Pure scraping functions only")
    print("📚 Preserving fashion history")
    print("=" * 50)
    
    app.run(host='127.0.0.1', port=8081, debug=True, threaded=True)