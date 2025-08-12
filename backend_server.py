#!/usr/bin/env python3
"""
Fashion Archive Backend Server
Bridges React UI to existing Python functionality maintaining exact same behavior
"""

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import os
import sys
import threading
from pathlib import Path

# Import existing Fashion Archive modules
sys.path.append(os.path.dirname(__file__))
from fashion_scraper import FashionScraper
import tkinter as tk

app = Flask(__name__)
CORS(app)

# Global reference to maintain Python backend state
class BackendService:
    def __init__(self):
        # Create a dummy tkinter root for the existing code
        self.root = tk.Tk()
        self.root.withdraw()  # Hide the tkinter window
        
        # Initialize the existing FashionScraper without UI
        self.scraper = FashionScraper(self.root)
        
    def get_seasons(self):
        """Get seasons using existing scraper logic"""
        try:
            # Use existing load_seasons method
            self.scraper.load_seasons()
            
            # Extract seasons data from scraper
            seasons = []
            if hasattr(self.scraper, 'seasons_data') and self.scraper.seasons_data:
                for season_info in self.scraper.seasons_data:
                    seasons.append({
                        'name': season_info.get('name', ''),
                        'url': season_info.get('url', ''),
                        'link_text': season_info.get('link_text', '')
                    })
            
            return seasons
        except Exception as e:
            print(f"Error getting seasons: {e}")
            return []
    
    def get_collections(self, season_url):
        """Get collections for a season using existing scraper logic"""
        try:
            # Use existing load_selected_season method
            # First find the season data
            season_data = None
            if hasattr(self.scraper, 'seasons_data'):
                for season in self.scraper.seasons_data:
                    if season.get('url') == season_url:
                        season_data = season
                        break
            
            if not season_data:
                return []
            
            # Set the current season
            self.scraper.current_season_url = season_url
            
            # Use existing method to load collections
            collections = []
            
            # This is complex - we need to trigger the existing threading logic
            # For now, return mock data that matches the structure
            # TODO: Extract collections loading logic from tkinter thread
            
            return collections
        except Exception as e:
            print(f"Error getting collections: {e}")
            return []
    
    def download_images(self, collection_data):
        """Download images using existing scraper logic"""
        try:
            # Use existing download_and_display_images method
            self.scraper.download_and_display_images(collection_data)
            
            # Wait for download to complete
            while self.scraper.is_downloading:
                threading.Event().wait(0.1)
            
            # Return the downloaded images
            return {
                'imagePaths': self.scraper.current_images.copy(),
                'designerName': collection_data.get('designer', ''),
                'error': None
            }
        except Exception as e:
            print(f"Error downloading images: {e}")
            return {
                'imagePaths': [],
                'designerName': collection_data.get('designer', ''),
                'error': str(e)
            }
    
    def download_video(self, collection_data):
        """Download video using existing video search logic"""
        try:
            if not hasattr(self.scraper, 'video_search_engine') or not self.scraper.video_search_engine:
                return None
                
            # Use existing video download logic
            collection_name = f"{collection_data.get('designer', '')} {collection_data.get('season', '')} {collection_data.get('year', '')}"
            
            # Call existing video download method
            video_path = self.scraper.video_search_engine.search_verify_and_download(collection_name)
            
            return video_path
        except Exception as e:
            print(f"Error downloading video: {e}")
            return None

# Global backend service instance
backend = BackendService()

@app.route('/api/seasons', methods=['POST'])
def get_seasons():
    """Get all available seasons"""
    try:
        seasons = backend.get_seasons()
        return jsonify({'seasons': seasons})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/collections', methods=['POST'])
def get_collections():
    """Get collections for a season"""
    try:
        data = request.get_json()
        season_url = data.get('seasonUrl', '')
        
        collections = backend.get_collections(season_url)
        return jsonify({'collections': collections})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download-images', methods=['POST'])
def download_images():
    """Download images for a collection"""
    try:
        data = request.get_json()
        collection = data.get('collection', {})
        
        result = backend.download_images(collection)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download-video', methods=['POST'])
def download_video():
    """Download video for a collection"""
    try:
        data = request.get_json()
        collection = data.get('collection', {})
        
        video_path = backend.download_video(collection)
        return jsonify({'videoPath': video_path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
    print("🎭 Fashion Archive Backend Server Starting...")
    print("🔗 Bridging React UI to Python backend")
    print("📚 Preserving fashion history for future generations")
    print("=" * 50)
    
    app.run(host='127.0.0.1', port=8080, debug=True, threaded=True)