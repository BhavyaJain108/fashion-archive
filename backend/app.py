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

import os
import sys

from flask import Flask, jsonify
from flask_cors import CORS

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Imports below sit after the sys.path insert above and cannot move to the top
# of the file; E402 is suppressed deliberately rather than left as lint noise.
from config.config import config  # noqa: E402

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
from backend.api.auth_routes import (  # noqa: E402
    PUBLIC_AUTH_ENDPOINTS,
    register_auth_routes,
)

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

# 6. Archive API (My Brands: the roster in brands.yml, served from the archive
# catalogue the scraper writes). Registered before install_auth so the hook below
# covers it like every other route.
try:
    print("🔧 Registering Archive API...")
    from backend.api.archive_routes import register_archive_routes
    register_archive_routes(app)
except Exception as e:
    print(f"❌ Error registering Archive API: {e}")
    import traceback
    traceback.print_exc()

# =============================================================================
# AUTHENTICATION
# =============================================================================
# Installed after every route is registered. The hook applies to all of them;
# only the endpoints named below are reachable without a session.

from backend.auth import db as auth_db  # noqa: E402
from backend.auth.email import ConsoleSender, ResendSender  # noqa: E402
from backend.auth.middleware import install_auth  # noqa: E402
from backend.auth.service import AuthService  # noqa: E402
from backend.storage import images as image_store  # noqa: E402

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

    # The show index ships as a file and is loaded on first boot. Seeding here
    # rather than by hand means a fresh deploy or a scratch database comes up
    # searchable, with no step anyone has to remember — and rebuilding it from
    # firstVIEW is 2,785 requests, which is not something a cold start should
    # ever quietly do.
    def _seed_show_index():
        from pathlib import Path

        from backend.high_fashion import firstview as fv
        from backend.high_fashion import show_index

        path = Path(__file__).parent / "high_fashion" / "shows.json.gz"
        if not path.exists():
            print("⚠️  show index file missing — browsing falls back to "
                  "crawling firstVIEW live")
            return
        try:
            with auth_db.transaction() as conn:
                if show_index.count(conn) > 0:
                    return
                data = fv.load_show_index(path)
                if not data:
                    print("⚠️  show index file unreadable or stale")
                    return
                written = show_index.seed(conn, data["shows"])
            print(f"✅ Show index seeded: {written:,} shows "
                  f"(built {data.get('built_on')})")
        except Exception as exc:  # noqa: BLE001 — a missing index is slow, not broken
            print(f"⚠️  show index seeding failed: {exc}")

    _seed_show_index()
else:
    print("⚠️  DATABASE_URL not set — authenticated endpoints will fail")

_store = image_store.configure(config)
if config.R2_ACCOUNT_ID:
    print(f"✅ Images -> R2 bucket '{config.R2_BUCKET}' at {config.R2_PUBLIC_BASE}")
else:
    print(f"⚠️  R2 not configured — images go to {config.IMAGE_CACHE_DIR} (lost on redeploy)")

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
    print("  ✓ High Fashion API (7 endpoints) - Seasons, collections, images, videos")
    print("  ✓ Favorites API (6 endpoints) - Favorite looks management (user-specific)")
    print("  ✓ Authentication API (4 endpoints) - User login & sessions")
    print("  ✓ Brand Following API (6 endpoints) - User brand following (user-specific)")
    print("")
    print("  Total: ~45 endpoints")
    print("")
    print("💡 Quick Start:")
    print("  GET  /api/health - Health check")
    print("  POST /api/seasons - Get fashion seasons")
    print("  GET  /api/favourites - Get favorite looks")
    print("")
    print("=" * 80)

    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)
