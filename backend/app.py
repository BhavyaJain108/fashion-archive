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
# Origins are restricted to the configured frontend. The previous setting
# combined origins="*" with supports_credentials=True, which browsers reject
# outright and which would be a blanket invitation if they did not: any site
# could call this API with the user's cookies attached.
CORS(app,
     resources={r"/api/*": {"origins": [config.APP_BASE_URL]}},
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
     allow_headers=['Content-Type'],
     supports_credentials=True)

# Made available to request handlers that need cookie flags.
app.config['APP_CONFIG'] = config
app.config['APP_BASE_URL'] = config.APP_BASE_URL

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
# Deliberately NOT wrapped in try/except. Every other module degrades to "that
# feature is missing"; auth failing to register would leave the site either
# fully open or fully locked out, so it must take the process down instead.
print("🔧 Registering Authentication API...")
from backend.api.auth_routes import PUBLIC_AUTH_ENDPOINTS, register_auth_routes
register_auth_routes(app)

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
# AUTHENTICATION
# =============================================================================
# Installed after every route is registered. The hook applies to all of them;
# only the endpoints named below are reachable without a session.

from backend.auth import db as auth_db
from backend.auth.email import ConsoleSender, ResendSender
from backend.auth.middleware import install_auth
from backend.auth.service import AuthService

if config.RESEND_API_KEY:
    _sender = ResendSender(config.RESEND_API_KEY, config.MAIL_FROM)
else:
    # No key configured: print verification links to stdout so local signup
    # works without credentials. Loud, because silently not sending email in
    # production would look like a delivery problem for a long time.
    print("⚠️  RESEND_API_KEY not set — verification emails will print to stdout")
    _sender = ConsoleSender()

app.extensions['auth_service'] = AuthService(
    sender=_sender,
    api_base_url=config.API_BASE_URL,
    app_base_url=config.APP_BASE_URL,
)

if config.DATABASE_URL:
    auth_db.init_pool(config.DATABASE_URL)
    print("✅ Postgres pool ready, auth schema applied")
else:
    print("⚠️  DATABASE_URL not set — authenticated endpoints will fail")

install_auth(app, public_endpoints={'health_check'} | PUBLIC_AUTH_ENDPOINTS)
print(f"🔒 Auth installed: {len(PUBLIC_AUTH_ENDPOINTS) + 1} public endpoints, "
      f"all others require a session")

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
