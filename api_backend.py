#!/usr/bin/env python3
"""
Fashion Archive API Backend
Uses the ORIGINAL working classes without ANY modifications
Just adds Flask API endpoints on top of the existing functionality
"""

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import os
import sys
import threading
import time
from pathlib import Path

app = Flask(__name__)
CORS(app)

# Import ALL the original modules exactly as they are
sys.path.append(os.path.dirname(__file__))

# Import original working classes - NO CHANGES
from image_downloader import ImageDownloader
try:
    from claude_video_verifier import EnhancedFashionVideoSearch
    VIDEO_FEATURES_AVAILABLE = True
except ImportError:
    VIDEO_FEATURES_AVAILABLE = False

# Import the original scraping logic from fashion_scraper.py
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse

class OriginalFashionAPI:
    """
    Wrapper that uses the ORIGINAL working scraping logic
    Copied directly from fashion_scraper.py with NO modifications
    """
    
    def __init__(self):
        self.base_url = "https://nowfashion.com"
        self.seasons_url = "https://nowfashion.com/fashion-week-seasons/"
        
        # EXACT headers from original
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Initialize video search exactly like original
        if VIDEO_FEATURES_AVAILABLE:
            self.video_search_engine = EnhancedFashionVideoSearch()
            print("🤖 AI-powered video verification enabled")
        else:
            self.video_search_engine = None
            print("⚠️ Video features not available")

    def load_seasons(self):
        """EXACT copy of load_seasons logic from fashion_scraper.py"""
        try:
            response = requests.get(self.seasons_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all links that look like fashion week seasons
            links = soup.find_all('a', href=True)
            season_links = []
            
            for link in links:
                href = link.get('href')
                text = link.get_text().strip()
                
                # Look for collection URLs
                if href and '/fashion/collections/' in href:
                    full_url = urljoin(self.base_url, href)
                    if text and len(text) > 5:  # Filter out empty or very short texts
                        season_links.append((text, full_url))
            
            # Remove duplicates and sort
            season_links = list(set(season_links))
            season_links.sort(key=lambda x: x[0])
            
            return season_links
            
        except Exception as e:
            print(f"Error loading seasons: {e}")
            return []

    def load_selected_season(self, season_url):
        """EXACT copy of load_selected_season logic from fashion_scraper.py"""
        try:
            collections = []
            page = 1
            
            while True:
                if page == 1:
                    current_url = season_url
                else:
                    current_url = f"{season_url.rstrip('/')}/page/{page}/"
                
                response = requests.get(current_url, headers=self.headers, timeout=10)
                
                # Handle 404 as end of pagination
                if response.status_code == 404:
                    print(f"Reached end of pagination (404) at page {page}")
                    break
                
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look specifically for h2 elements with wp-block-post-title class containing designer links
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
                
                # Check for various pagination patterns
                has_next_page = False
                
                # Method 1: Look for "Next" text link
                next_link = soup.find('a', string=re.compile(r'next|Next', re.IGNORECASE))
                if next_link:
                    has_next_page = True
                
                # Method 2: Look for pagination with numbered links
                if not has_next_page:
                    pagination_area = soup.find('nav', class_=re.compile(r'pagination|nav-links')) or soup.find('div', class_=re.compile(r'pagination|nav-links'))
                    if pagination_area:
                        # Look for a link to the next page number
                        next_page_link = pagination_area.find('a', href=re.compile(f'/page/{page + 1}'))
                        if next_page_link:
                            has_next_page = True
                
                # Method 3: Look for arrow-based navigation
                if not has_next_page:
                    arrow_next = soup.find('a', string=re.compile(r'[›→]|&gt;|&#8250;'))
                    if arrow_next:
                        has_next_page = True
                
                # Method 4: Continue if we got collections
                if not has_next_page and len(page_collections) > 0:
                    has_next_page = True
                
                if not has_next_page:
                    break
                
                page += 1
            
            # If no collections found at all, try fallback method
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
            
            # Remove duplicates based on designer name
            unique_collections = []
            seen_designers = set()
            
            for collection in collections:
                designer_key = collection['designer'].lower().strip()
                if designer_key not in seen_designers:
                    seen_designers.add(designer_key)
                    unique_collections.append(collection)
            
            # SORT ALPHABETICALLY - this was missing!
            unique_collections.sort(key=lambda x: x['designer'].lower())
            
            return unique_collections
            
        except Exception as e:
            print(f"Error loading collections: {e}")
            return []

    def download_images(self, collection):
        """Use the ORIGINAL ImageDownloader class exactly as is"""
        try:
            # Import the original DownloadConfig
            from image_downloader import DownloadConfig
            
            # Create config using the ORIGINAL DownloadConfig class
            config = DownloadConfig(
                url=collection['url'],
                output_dir='downloads',
                max_images=50,
                delay=1.0,
                timeout=30,
                retries=3,
                user_agent=self.headers['User-Agent']
            )
            
            # Use the original ImageDownloader
            downloader = ImageDownloader(config)
            downloaded_files = downloader.download_images()
            
            return {
                'success': True,
                'imagePaths': downloaded_files or [],
                'designerName': collection['designer'],
                'count': len(downloaded_files) if downloaded_files else 0
            }
            
        except Exception as e:
            return {
                'success': False,
                'imagePaths': [],
                'designerName': collection.get('designer', 'Unknown'),
                'error': str(e)
            }

    def download_video(self, collection):
        """Use the ORIGINAL video search exactly as is"""
        try:
            if not self.video_search_engine:
                return None
                
            collection_name = f"{collection.get('designer', '')} {collection.get('season', '')} {collection.get('year', '')}"
            video_path = self.video_search_engine.search_verify_and_download(collection_name)
            return video_path
            
        except Exception as e:
            print(f"Video download error: {e}")
            return None

# Global API instance using original classes
api = OriginalFashionAPI()

@app.route('/api/seasons', methods=['POST'])
def get_seasons():
    """Get seasons using original logic"""
    try:
        season_links = api.load_seasons()
        seasons = []
        for text, url in season_links:
            seasons.append({
                'name': text,
                'url': url,
                'href': url.replace(api.base_url, '')
            })
        return jsonify({'seasons': seasons, 'success': True})
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/collections', methods=['POST'])
def get_collections():
    """Get collections using original logic"""
    try:
        data = request.get_json()
        season_url = data.get('seasonUrl', '')
        
        collections = api.load_selected_season(season_url)
        return jsonify({'collections': collections, 'success': True})
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/download-images', methods=['POST'])
def download_images():
    """Download images using original logic"""
    try:
        data = request.get_json()
        collection = data.get('collection', {})
        
        result = api.download_images(collection)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/download-video', methods=['POST'])
def download_video():
    """Download video using original logic"""
    try:
        data = request.get_json()
        collection = data.get('collection', {})
        
        video_path = api.download_video(collection)
        return jsonify({'videoPath': video_path, 'success': True})
    except Exception as e:
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
    print("🎭 Fashion Archive API Backend Starting...")
    print("🔗 Using ORIGINAL working classes with NO modifications")
    print("📚 Preserving fashion history for future generations")
    print("=" * 50)
    
    app.run(host='127.0.0.1', port=8081, debug=True, threaded=True)