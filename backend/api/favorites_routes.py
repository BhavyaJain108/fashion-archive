"""
Favorites API Routes
====================

Endpoints for managing favorite high-fashion looks (user-specific)
"""

from flask import jsonify, request

# Import the favorites database and auth middleware
from backend.high_fashion.favourites_db import FavouritesDB
from backend.auth.user_system.middleware import get_current_user


def get_favourites():
    """GET /api/favourites - Get all favourite looks for current user"""
    try:
        # Get current user from session
        user = get_current_user()

        # Get user-specific favourites database
        user_favourites_dir = user.get_data_path("favourites")
        favourites_db = FavouritesDB(user_favourites_dir)

        favourites = favourites_db.get_all_favourites()
        return jsonify({'favourites': favourites})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def add_favourite():
    """POST /api/favourites - Add a look to favourites for current user"""
    try:
        # Get current user from session
        user = get_current_user()

        # Get user-specific favourites database
        user_favourites_dir = user.get_data_path("favourites")
        favourites_db = FavouritesDB(user_favourites_dir)

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


def remove_favourite():
    """DELETE /api/favourites - Remove a look from favourites for current user"""
    try:
        # Get current user from session
        user = get_current_user()

        # Get user-specific favourites database
        user_favourites_dir = user.get_data_path("favourites")
        favourites_db = FavouritesDB(user_favourites_dir)

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


def check_favourite():
    """POST /api/favourites/check - Check if a look is favourited for current user"""
    try:
        # Get current user from session
        user = get_current_user()

        # Get user-specific favourites database
        user_favourites_dir = user.get_data_path("favourites")
        favourites_db = FavouritesDB(user_favourites_dir)

        data = request.get_json()

        season_url = data.get('season_url', '')
        collection_url = data.get('collection_url', '')
        look_number = data.get('look_number', 0)

        is_fav = favourites_db.is_favourite(season_url, collection_url, look_number)

        return jsonify({'is_favourite': is_fav})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_favourites_stats():
    """GET /api/favourites/stats - Get favourites statistics for current user"""
    try:
        # Get current user from session
        user = get_current_user()

        # Get user-specific favourites database
        user_favourites_dir = user.get_data_path("favourites")
        favourites_db = FavouritesDB(user_favourites_dir)

        stats = favourites_db.get_stats()
        return jsonify({'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def cleanup_favourites():
    """POST /api/favourites/cleanup - Clean up orphaned images for current user"""
    try:
        # Get current user from session
        user = get_current_user()

        # Get user-specific favourites database
        user_favourites_dir = user.get_data_path("favourites")
        favourites_db = FavouritesDB(user_favourites_dir)

        removed_count = favourites_db.cleanup_orphaned_images()
        return jsonify({
            'success': True,
            'message': f'Cleaned up {removed_count} orphaned images',
            'removed_count': removed_count
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def register_favorites_routes(app):
    """Register all favorites routes (all require authentication)"""
    from functools import wraps
    from backend.auth.user_system.middleware import require_auth

    # Apply auth middleware to all endpoints
    @wraps(get_favourites)
    @require_auth
    def protected_get_favourites():
        return get_favourites()

    @wraps(add_favourite)
    @require_auth
    def protected_add_favourite():
        return add_favourite()

    @wraps(remove_favourite)
    @require_auth
    def protected_remove_favourite():
        return remove_favourite()

    @wraps(check_favourite)
    @require_auth
    def protected_check_favourite():
        return check_favourite()

    @wraps(get_favourites_stats)
    @require_auth
    def protected_get_favourites_stats():
        return get_favourites_stats()

    @wraps(cleanup_favourites)
    @require_auth
    def protected_cleanup_favourites():
        return cleanup_favourites()

    app.add_url_rule('/api/favourites', 'get_favourites', protected_get_favourites, methods=['GET'])
    app.add_url_rule('/api/favourites', 'add_favourite', protected_add_favourite, methods=['POST'])
    app.add_url_rule('/api/favourites', 'remove_favourite', protected_remove_favourite, methods=['DELETE'])
    app.add_url_rule('/api/favourites/check', 'check_favourite', protected_check_favourite, methods=['POST'])
    app.add_url_rule('/api/favourites/stats', 'get_favourites_stats', protected_get_favourites_stats, methods=['GET'])
    app.add_url_rule('/api/favourites/cleanup', 'cleanup_favourites', protected_cleanup_favourites, methods=['POST'])

    print("✅ Favorites API routes registered (6 endpoints, all require auth)")
