#!/usr/bin/env python3
"""
Headless Fashion Archive Backend
Extracts core functionality without tkinter dependencies
"""

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse
import os
from pathlib import Path
import threading
import time

app = Flask(__name__)
CORS(app)

class HeadlessFashionScraper:
    """
    Headless version of FashionScraper without tkinter dependencies
    Maintains exact same functionality but returns data instead of updating UI
    """
    
    def __init__(self):
        self.base_url = "https://nowfashion.com"
        self.seasons_url = "https://nowfashion.com/fashion-week-seasons/"
        
        # Headers to avoid 403 errors (same as tkinter version)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Initialize video search if available
        self.video_search_engine = None
        try:
            from claude_video_verifier import EnhancedFashionVideoSearch
            self.video_search_engine = EnhancedFashionVideoSearch()
            print("🤖 AI-powered video verification enabled")
        except ImportError as e:
            print(f"⚠️ Video features not available: {e}")

    def get_seasons(self):
        """Get all seasons - EXACT copy from working tkinter version"""
        try:
            print("🔍 Fetching seasons from nowfashion.com...")
            response = requests.get(self.seasons_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all links that look like fashion week seasons (EXACT tkinter logic)
            links = soup.find_all('a', href=True)
            season_links = []
            
            for link in links:
                href = link.get('href')
                text = link.get_text().strip()
                
                # Look for collection URLs (EXACT tkinter logic)
                if href and '/fashion/collections/' in href:
                    full_url = urljoin(self.base_url, href)
                    if text and len(text) > 5:  # Filter out empty or very short texts
                        season_links.append((text, full_url))
            
            # Remove duplicates and sort (EXACT tkinter logic)
            season_links = list(set(season_links))
            season_links.sort(key=lambda x: x[0])
            
            # Convert to expected format
            seasons = []
            for text, url in season_links:
                seasons.append({
                    'name': text,
                    'url': url,
                    'href': url.replace(self.base_url, '')
                })
            
            print(f"✅ Found {len(seasons)} seasons")
            return seasons
            
        except Exception as e:
            print(f"❌ Error fetching seasons: {e}")
            return []

    def get_collections(self, season_url):
        """Get collections for a season - EXACT copy from working tkinter version"""
        try:
            print(f"🔍 Fetching collections for season: {season_url}")
            
            collections = []
            page = 1
            
            while True:
                # Build page URL (EXACT tkinter logic)
                if page == 1:
                    current_url = season_url
                else:
                    current_url = f"{season_url.rstrip('/')}/page/{page}/"
                
                print(f"📄 Loading page {page}: {current_url}")
                
                response = requests.get(current_url, headers=self.headers, timeout=10)
                
                # Handle 404 as end of pagination (EXACT tkinter logic)
                if response.status_code == 404:
                    print(f"Reached end of pagination (404) at page {page}")
                    break
                
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look specifically for h2 elements with wp-block-post-title class containing designer links (EXACT tkinter logic)
                h2_elements = soup.find_all('h2', class_='wp-block-post-title')
                
                if not h2_elements:
                    # No more collections found, break
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
                    # No collections found on this page, break
                    break
                
                collections.extend(page_collections)
                print(f"📄 Page {page}: Found {len(page_collections)} collections (total: {len(collections)})")
                
                # Check for various pagination patterns (EXACT tkinter logic)
                has_next_page = False
                
                # Method 1: Look for "Next" text link
                next_link = soup.find('a', string=re.compile(r'next|Next', re.IGNORECASE))
                if next_link:
                    has_next_page = True
                    print(f"Found 'Next' link: {next_link}")
                
                # Method 2: Look for pagination with numbered links
                if not has_next_page:
                    pagination_area = soup.find('nav', class_=re.compile(r'pagination|nav-links')) or soup.find('div', class_=re.compile(r'pagination|nav-links'))
                    if pagination_area:
                        # Look for a link to the next page number
                        next_page_link = pagination_area.find('a', href=re.compile(f'/page/{page + 1}'))
                        if next_page_link:
                            has_next_page = True
                            print(f"Found next page link in pagination: {next_page_link}")
                
                # Method 3: Look for arrow-based navigation (›, →, etc.)
                if not has_next_page:
                    arrow_next = soup.find('a', string=re.compile(r'[›→]|&gt;|&#8250;'))
                    if arrow_next:
                        has_next_page = True
                        print(f"Found arrow next link: {arrow_next}")
                
                # Method 4: Check if we got fewer results than expected (might indicate last page)
                if not has_next_page and len(page_collections) > 0:
                    # Continue to next page anyway if we got collections (naive approach)
                    has_next_page = True
                    print(f"No pagination found but got {len(page_collections)} collections, trying next page")
                
                if not has_next_page:
                    print(f"No more pages found after page {page}")
                    break
                
                page += 1
            
            # If no collections found at all, try fallback method on first page (EXACT tkinter logic)
            if len(collections) == 0:
                response = requests.get(season_url, headers=self.headers, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for any links that might contain fashion show information
                fashion_links = soup.find_all('a', href=re.compile(r'fashion|show|collection', re.I))
                
                for link in fashion_links:
                    href = link.get('href')
                    text = link.get_text().strip()
                    
                    if href and text and len(text) > 3:
                        collections.append({
                            'designer': text,
                            'photos': '',
                            'date': '',
                            'url': href,
                            'text': text
                        })
            
            # Remove duplicates (EXACT tkinter logic)
            unique_collections = []
            seen_designers = set()
            
            for collection in collections:
                designer_key = collection['designer'].lower().strip()
                if designer_key not in seen_designers:
                    seen_designers.add(designer_key)
                    unique_collections.append(collection)
            
            print(f"✅ Found {len(unique_collections)} unique collections")
            return unique_collections
            
        except Exception as e:
            print(f"❌ Error fetching collections: {e}")
            return []

    def download_images(self, collection):
        """Download images for a collection - uses existing image_downloader.py"""
        try:
            from image_downloader import ImageDownloader
            
            print(f"📥 Starting image download for: {collection['designer']}")
            
            # Create download config (same as tkinter version)
            config = type('obj', (object,), {
                'url': collection['url'],
                'output_dir': 'downloads',
                'max_images': 50,
                'delay': 1.0,
                'timeout': 30,
                'user_agent': self.headers['User-Agent']
            })()
            
            # Create downloader and download
            downloader = ImageDownloader(config)
            
            try:
                downloaded_files = downloader.download_images()
                
                if downloaded_files:
                    print(f"✅ Downloaded {len(downloaded_files)} images")
                    return {
                        'success': True,
                        'imagePaths': downloaded_files,
                        'designerName': collection['designer'],
                        'count': len(downloaded_files)
                    }
                else:
                    print("❌ No images were downloaded")
                    return {
                        'success': False,
                        'imagePaths': [],
                        'designerName': collection['designer'],
                        'error': 'No images found or downloaded'
                    }
                    
            except Exception as download_error:
                print(f"❌ Download error: {download_error}")
                return {
                    'success': False,
                    'imagePaths': [],
                    'designerName': collection['designer'],
                    'error': str(download_error)
                }
                
        except Exception as e:
            print(f"❌ Error in download_images: {e}")
            return {
                'success': False,
                'imagePaths': [],
                'designerName': collection.get('designer', 'Unknown'),
                'error': str(e)
            }

    def download_video(self, collection):
        """Download video for a collection - uses existing video system"""
        try:
            if not self.video_search_engine:
                print("⚠️ Video search engine not available")
                return None
                
            collection_name = f"{collection.get('designer', '')} {collection.get('season', '')} {collection.get('year', '')}"
            print(f"🎬 Searching for video: {collection_name}")
            
            # Use existing video search and download
            video_path = self.video_search_engine.search_verify_and_download(collection_name)
            
            if video_path:
                print(f"✅ Video downloaded: {video_path}")
                return video_path
            else:
                print("❌ No video found or downloaded")
                return None
                
        except Exception as e:
            print(f"❌ Video download error: {e}")
            return None

# Global backend instance
backend = HeadlessFashionScraper()

@app.route('/api/seasons', methods=['POST'])
def get_seasons():
    """Get all available seasons"""
    try:
        seasons = backend.get_seasons()
        return jsonify({'seasons': seasons, 'success': True})
    except Exception as e:
        print(f"API Error - get_seasons: {e}")
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/collections', methods=['POST'])
def get_collections():
    """Get collections for a season"""
    try:
        data = request.get_json()
        season_url = data.get('seasonUrl', '')
        
        if not season_url:
            return jsonify({'error': 'Season URL required', 'success': False}), 400
        
        collections = backend.get_collections(season_url)
        return jsonify({'collections': collections, 'success': True})
    except Exception as e:
        print(f"API Error - get_collections: {e}")
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/download-images', methods=['POST'])
def download_images():
    """Download images for a collection"""
    try:
        data = request.get_json()
        collection = data.get('collection', {})
        
        if not collection:
            return jsonify({'error': 'Collection data required', 'success': False}), 400
        
        result = backend.download_images(collection)
        return jsonify(result)
    except Exception as e:
        print(f"API Error - download_images: {e}")
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/download-video', methods=['POST'])
def download_video():
    """Download video for a collection"""
    try:
        data = request.get_json()
        collection = data.get('collection', {})
        
        video_path = backend.download_video(collection)
        return jsonify({'videoPath': video_path, 'success': True})
    except Exception as e:
        print(f"API Error - download_video: {e}")
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/image')
def serve_image():
    """Serve image files"""
    try:
        image_path = request.args.get('path', '')
        if not image_path or not os.path.exists(image_path):
            return jsonify({'error': 'Image not found'}), 404
            
        return send_file(image_path)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/video')
def serve_video():
    """Serve video files"""
    try:
        video_path = request.args.get('path', '')
        if not video_path or not os.path.exists(video_path):
            return jsonify({'error': 'Video not found'}), 404
            
        return send_file(video_path)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🎭 Fashion Archive Headless Backend Starting...")
    print("🔗 Bridging React UI to Python core functionality")
    print("📚 Preserving fashion history for future generations")
    print("=" * 50)
    
    app.run(host='127.0.0.1', port=8080, debug=True, threaded=True)