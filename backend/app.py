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
from config.config import config

# Create Flask app
app = Flask(__name__)
CORS(app,
     resources={r"/api/*": {"origins": "*"}},
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization'],
     supports_credentials=True)

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

# 1. Premium Scraper API (unified brand management system)
try:
    print("🔧 Registering Premium Scraper API...")
    from backend.api import register_routes
    register_routes(app)
    print("✅ Premium Scraper API registered (22 endpoints)")
except Exception as e:
    print(f"❌ Error registering Premium Scraper API: {e}")
    import traceback
    traceback.print_exc()

# 2. High Fashion API (seasons, collections, images, videos)
try:
    print("🔧 Registering High Fashion API...")
    from backend.api.high_fashion_routes import register_high_fashion_routes
    register_high_fashion_routes(app)
except Exception as e:
    print(f"❌ Error registering High Fashion API: {e}")
    import traceback
    traceback.print_exc()

# 3. Favorites API (favorite looks management)
try:
    print("🔧 Registering Favorites API...")
    from backend.api.favorites_routes import register_favorites_routes
    register_favorites_routes(app)
except Exception as e:
    print(f"❌ Error registering Favorites API: {e}")
    import traceback
    traceback.print_exc()

# 4. Authentication API (user login/session management)
try:
    print("🔧 Registering Authentication API...")
    from backend.api.auth_routes import register_auth_routes
    register_auth_routes(app)
except Exception as e:
    print(f"❌ Error registering Authentication API: {e}")
    import traceback
    traceback.print_exc()

# 5. Brand Following API (user brand following management)
try:
    print("🔧 Registering Brand Following API...")
    from backend.api.brand_following_routes import register_brand_following_routes
    register_brand_following_routes(app)
except Exception as e:
    print(f"❌ Error registering Brand Following API: {e}")
    import traceback
    traceback.print_exc()

# =============================================================================
# RUN SERVER
# =============================================================================

if __name__ == '__main__':
    print("=" * 80)
    print("🎭 Fashion Archive - Unified Backend API")
    print("=" * 80)
    print(f"📍 Host: {config.HOST}")
    print(f"🔌 Port: {config.PORT}")
    print(f"🐛 Debug: {config.DEBUG}")
    print("=" * 80)
    print("")
    print("📦 Registered API Groups:")
    print("  ✓ Premium Scraper API (22 endpoints) - Brand & product management")
    print("  ✓ High Fashion API (7 endpoints) - Seasons, collections, images, videos")
    print("  ✓ Favorites API (6 endpoints) - Favorite looks management (user-specific)")
    print("  ✓ Authentication API (4 endpoints) - User login & sessions")
    print("  ✓ Brand Following API (6 endpoints) - User brand following (user-specific)")
    print("")
    print(f"  Total: ~45 endpoints")
    print("")
    print("💡 Quick Start:")
    print("  GET  /api/health - Health check")
    print("  GET  /api/brands - List all brands")
    print("  POST /api/seasons - Get fashion seasons")
    print("  GET  /api/favourites - Get favorite looks")
    print("")
    print("=" * 80)

    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)
