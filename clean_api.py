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
from favourites_db import favourites_db
from config import config

# Import user system
from user_system.auth import UserAuth
from user_system.middleware import require_auth, get_current_user

app = Flask(__name__)
CORS(app, methods=['GET', 'POST', 'DELETE', 'OPTIONS'])

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
        # Import with explicit module loading to avoid conflicts
        import importlib.util
        import os
        
        # Load the root image_downloader module directly
        spec = importlib.util.spec_from_file_location(
            "main_image_downloader", 
            os.path.join(os.path.dirname(__file__), "image_downloader.py")
        )
        main_img_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main_img_module)
        
        ImageDownloader = main_img_module.ImageDownloader
        DownloadConfig = main_img_module.DownloadConfig
        
        data = request.get_json()
        collection = data.get('collection', {})
        
        config = DownloadConfig(
            url=collection['url'],
            output_dir='high_fashion_cache/images',
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
            
            # Also check what's actually in the images folder
            images_path = Path("high_fashion_cache/images")
            if images_path.exists():
                actual_files = list(images_path.glob("*"))
                print(f"Files actually in images folder: {len(actual_files)}")
                # Use actual files from images folder instead
                existing_images = [str(f) for f in actual_files if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.webp']]
                print(f"Found {len(existing_images)} image files in images folder")
            
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
            'designerName': collection.get('designer', 'Unknown'),
            'count': len(final_images)
        })
        
    except Exception as e:
        # Handle case where collection might not be defined yet
        designer_name = 'Unknown'
        try:
            if 'collection' in locals():
                designer_name = collection.get('designer', 'Unknown')
        except:
            pass
        
        return jsonify({
            'success': False,
            'imagePaths': [],
            'designerName': designer_name,
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

@app.route('/api/stream-video', methods=['POST'])
def stream_video():
    """Get streaming URL for direct video playback"""
    try:
        # Only import if available
        try:
            from claude_video_verifier import EnhancedFashionVideoSearch
            video_search_engine = EnhancedFashionVideoSearch()
        except ImportError:
            return jsonify({'streamingUrl': None, 'success': False, 'error': 'Video search not available'})
        
        data = request.get_json()
        collection = data.get('collection', {})
        
        collection_name = f"{collection.get('designer', '')} {collection.get('season', '')} {collection.get('year', '')}"
        streaming_info = video_search_engine.get_streaming_url(collection_name)
        
        if streaming_info:
            return jsonify({
                'success': True,
                'videoId': streaming_info['video_id'],
                'youtubeUrl': streaming_info['youtube_url'],
                'embedUrl': streaming_info['embed_url'],
                'title': streaming_info['title'],
                'thumbnail': streaming_info['thumbnail']
            })
        else:
            return jsonify({'streamingUrl': None, 'success': False, 'error': 'No streaming URL found'})
        
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/image')
def serve_image_legacy():
    """Legacy image endpoint - use /api/images/{brand}/{category}/{filename} instead"""
    try:
        image_path = request.args.get('path', '')
        if not image_path or not os.path.exists(image_path):
            return jsonify({'error': 'Image not found'}), 404
        return send_file(image_path)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup', methods=['POST'])
def cleanup_downloads():
    """Clean up previous downloads and videos (matches tkinter cleanup_previous_downloads)"""
    try:
        import shutil
        from pathlib import Path
        
        # Clean images cache
        images_path = Path("high_fashion_cache/images")
        if images_path.exists():
            # Remove all files in images directory
            for item in images_path.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            print(f"Cleaned images cache folder")
        
        # Clean videos cache (matches tkinter clear_videos_folder)
        videos_path = Path("high_fashion_cache/videos")
        if videos_path.exists():
            for item in videos_path.iterdir():
                if item.is_file():
                    item.unlink()
            print(f"Cleaned videos cache folder")
        
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

# Favourites API Endpoints

@app.route('/api/favourites', methods=['GET'])
def get_favourites():
    """Get all favourite looks"""
    try:
        favourites = favourites_db.get_all_favourites()
        return jsonify({'favourites': favourites})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/favourites', methods=['POST'])
def add_favourite():
    """Add a look to favourites"""
    try:
        data = request.get_json()
        
        season_data = data.get('season', {})
        collection_data = data.get('collection', {})
        look_data = data.get('look', {})
        image_path = data.get('image_path', '')
        notes = data.get('notes', '')
        
        success = favourites_db.add_favourite(
            season_data, collection_data, look_data, image_path, notes
        )
        
        if success:
            return jsonify({'success': True, 'message': 'Added to favourites'})
        else:
            return jsonify({'success': False, 'message': 'Already in favourites'})
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/favourites', methods=['DELETE'])
def remove_favourite():
    """Remove a look from favourites"""
    try:
        data = request.get_json()
        
        season_url = data.get('season_url', '')
        collection_url = data.get('collection_url', '')
        look_number = data.get('look_number', 0)
        
        success = favourites_db.remove_favourite(season_url, collection_url, look_number)
        
        if success:
            return jsonify({'success': True, 'message': 'Removed from favourites'})
        else:
            return jsonify({'success': False, 'message': 'Not found in favourites'})
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/favourites/check', methods=['POST'])
def check_favourite():
    """Check if a look is favourited"""
    try:
        data = request.get_json()
        
        season_url = data.get('season_url', '')
        collection_url = data.get('collection_url', '')
        look_number = data.get('look_number', 0)
        
        is_fav = favourites_db.is_favourite(season_url, collection_url, look_number)
        
        return jsonify({'is_favourite': is_fav})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/favourites/stats', methods=['GET'])
def get_favourites_stats():
    """Get favourites statistics"""
    try:
        stats = favourites_db.get_stats()
        return jsonify({'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/favourites/cleanup', methods=['POST'])
def cleanup_favourites():
    """Clean up orphaned images in favourites directory"""
    try:
        removed_count = favourites_db.cleanup_orphaned_images()
        return jsonify({
            'success': True, 
            'message': f'Cleaned up {removed_count} orphaned images',
            'removed_count': removed_count
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Register My Brands API endpoints (DISABLED - using unified API instead)
# try:
#     from my_brands.brands_api import register_brands_endpoints
#     register_brands_endpoints(app)
#     print("✅ My Brands API endpoints registered")
# except ImportError as e:
#     print(f"⚠️  My Brands endpoints not available: {e}")

# Register Premium Scraper API endpoints (legacy - deprecated)
try:
    import sys
    import os

    from backend.scraper.api import PremiumScraperAPI
    
    # Create API instance
    premium_api = PremiumScraperAPI()
    
    @app.route('/api/premium/test', methods=['GET'])
    def test_premium_api():
        """Test endpoint to verify premium API is working"""
        return jsonify({
            'success': True,
            'message': 'Premium Scraper API is integrated and running',
            'version': '1.0.0',
            'endpoints': [
                'POST /api/premium/scrape - Start a scraping job',
                'GET /api/premium/scrape/<job_id> - Get job status',
                'GET /api/premium/scrape/<job_id>/products - Get scraped products',
                'GET /api/premium/scrape/<job_id>/download - Download results as CSV',
                'GET /api/premium/jobs - List all jobs',
                'POST /api/premium/analyze - Analyze brand for scraping'
            ]
        })
    
    @app.route('/api/premium/scrape', methods=['POST'])
    def start_premium_scrape():
        """Start a premium scraping job"""
        result, status_code = premium_api.start_scrape()
        return jsonify(result), status_code
    
    @app.route('/api/premium/scrape/<job_id>', methods=['GET'])
    def get_scrape_status(job_id):
        """Get the status of a scraping job"""
        result, status_code = premium_api.get_job_status(job_id)
        return jsonify(result), status_code
    
    @app.route('/api/premium/scrape/<job_id>/products', methods=['GET'])
    def get_scrape_products(job_id):
        """Get products from a completed scraping job"""
        result, status_code = premium_api.get_job_products(job_id)
        return jsonify(result), status_code
    
    @app.route('/api/premium/scrape/<job_id>/download', methods=['GET'])
    def download_scrape_results(job_id):
        """Download the CSV results of a completed scraping job"""
        return premium_api.download_results(job_id)
    
    @app.route('/api/premium/jobs', methods=['GET'])
    def list_scraping_jobs():
        """List all scraping jobs"""
        result, status_code = premium_api.list_jobs()
        return jsonify(result), status_code
    
    @app.route('/api/premium/analyze', methods=['POST'])
    def analyze_brand_premium():
        """Analyze a brand website for scraping compatibility"""
        result, status_code = premium_api.analyze_brand()
        return jsonify(result), status_code
    
    print("✅ Premium Scraper API endpoints registered")
    
except ImportError as e:
    print(f"⚠️  Premium Scraper endpoints not available: {e}")
except Exception as e:
    print(f"❌ Error registering Premium Scraper endpoints: {e}")

# =============================================================================
# USER AUTHENTICATION ENDPOINTS
# =============================================================================

# Initialize user auth system
user_auth = UserAuth()

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    """Login or register user with name/password"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        action = data.get('action', 'login')  # 'login' or 'register'
        
        # Validate input
        if not username or not password:
            return jsonify({
                'success': False,
                'error': 'Username and password are required'
            }), 400
        
        # Enforce username length limit
        if len(username) > 35:
            return jsonify({
                'success': False,
                'error': 'Username must be 35 characters or less'
            }), 400
        
        if action == 'register':
            # Register new user
            success, user, session, message = user_auth.register(username, password, username)
        else:
            # Try login first, then check if we should offer registration
            success, user, session, message = user_auth.get_or_create_user(username, password)
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'user_folder': user.user_folder
                },
                'session_token': session.token
            })
        else:
            # Check if this is a "user not found" case for registration prompt
            if "not found. Would you like to create" in message:
                return jsonify({
                    'success': False,
                    'error': message,
                    'can_register': True,
                    'username': username
                }), 404
            else:
                return jsonify({
                    'success': False,
                    'error': message,
                    'can_register': False
                }), 401
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Authentication failed: {str(e)}'
        }), 500

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    """Logout user by invalidating session"""
    try:
        data = request.get_json()
        session_token = data.get('session_token')
        
        if not session_token:
            return jsonify({
                'success': False,
                'error': 'Session token required'
            }), 400
        
        success = user_auth.logout(session_token)
        
        return jsonify({
            'success': success,
            'message': 'Logged out successfully' if success else 'Logout failed'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Logout failed: {str(e)}'
        }), 500

@app.route('/api/auth/me', methods=['GET'])
@require_auth
def auth_me():
    """Get current user profile"""
    try:
        user = get_current_user()
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'display_name': user.display_name,
                'user_folder': user.user_folder,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'last_login': user.last_login.isoformat() if user.last_login else None
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get user profile: {str(e)}'
        }), 500

@app.route('/api/auth/validate', methods=['POST'])
def auth_validate():
    """Validate session token without requiring authentication middleware"""
    try:
        data = request.get_json()
        session_token = data.get('session_token')
        
        if not session_token:
            return jsonify({
                'success': False,
                'valid': False,
                'error': 'Session token required'
            }), 400
        
        valid, user, message = user_auth.validate_session(session_token)
        
        if valid:
            return jsonify({
                'success': True,
                'valid': True,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'display_name': user.display_name,
                    'user_folder': user.user_folder
                }
            })
        else:
            return jsonify({
                'success': True,
                'valid': False,
                'error': message
            })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'valid': False,
            'error': f'Validation failed: {str(e)}'
        }), 500

# =============================================================================
# UNIFIED PREMIUM SCRAPER API
# =============================================================================

try:
    print("🔧 Registering Unified Premium Scraper API...")
    from backend.api import register_routes
    register_routes(app)
except ImportError as e:
    print(f"⚠️  Unified API not available: {e}")
except Exception as e:
    print(f"❌ Error registering Unified API: {e}")

if __name__ == '__main__':
    print("🎭 Clean API Backend - NO tkinter dependencies")
    print("🔗 Pure scraping functions only")
    print("📚 Preserving fashion history")
    print("=" * 50)

    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)