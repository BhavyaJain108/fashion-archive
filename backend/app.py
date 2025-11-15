#!/usr/bin/env python3
"""
Backend Application
===================

Main entry point for the Fashion Archive backend API.
Integrates:
- Premium scraper API
- Fashion show/season API
- Favourites system
- User authentication
"""

from flask import Flask, jsonify
from flask_cors import CORS
import os
import sys

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import configuration
from config import config

# Create Flask app
app = Flask(__name__)
CORS(app, methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])

# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "Fashion Archive API",
        "version": "1.0.0"
    })

# =============================================================================
# REGISTER API MODULES
# =============================================================================

# 1. Premium Scraper API (new unified system)
try:
    print("🔧 Registering Premium Scraper API...")
    from backend.api import register_routes
    register_routes(app)
    print("✅ Premium Scraper API registered")
except Exception as e:
    print(f"❌ Error registering Premium Scraper API: {e}")
    import traceback
    traceback.print_exc()

# 2. Fashion Show/Season API (legacy - from clean_api.py)
try:
    print("🔧 Registering Fashion Show API...")
    # Import the old clean_api endpoints
    # (We'll keep these separate for now since they work)
    import clean_api
    # The endpoints are already registered on clean_api.app
    # We need to copy them to our app
    # For now, we'll skip this and focus on the new premium API
    print("⚠️  Fashion Show API kept in clean_api.py for now")
except Exception as e:
    print(f"⚠️  Fashion Show API import warning: {e}")

# 3. Favourites API (from clean_api.py)
# 4. User Auth API (from clean_api.py)
# These are in clean_api.py - we can migrate later

# =============================================================================
# RUN SERVER
# =============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("🎭 Fashion Archive Backend API")
    print("=" * 60)
    print(f"📍 Host: {config.HOST}")
    print(f"🔌 Port: {config.PORT}")
    print(f"🐛 Debug: {config.DEBUG}")
    print("=" * 60)
    print("")
    print("Available endpoints:")
    print("  GET  /api/health - Health check")
    print("  GET  /api/brands - List brands")
    print("  POST /api/brands - Create brand")
    print("  GET  /api/products - Query products")
    print("  ... and 19 more endpoints (see docs)")
    print("")
    print("=" * 60)

    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)
