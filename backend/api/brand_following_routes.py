"""
Brand Following API Routes
===========================

Endpoints for managing which brands a user follows
"""

from flask import jsonify, request
from backend.auth.user_system.middleware import get_current_user
from backend.auth.user_system.brand_following import BrandFollowing


def follow_brand():
    """POST /api/brands/follow - Follow a brand"""
    try:
        user = get_current_user()
        brand_following = BrandFollowing(user.user_folder)

        data = request.get_json()
        brand_id = data.get('brand_id', '')
        brand_name = data.get('brand_name', '')
        notes = data.get('notes', '')

        if not brand_id or not brand_name:
            return jsonify({
                'success': False,
                'error': 'brand_id and brand_name are required'
            }), 400

        success, message = brand_following.follow_brand(brand_id, brand_name, notes)

        return jsonify({
            'success': success,
            'message': message
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def unfollow_brand():
    """POST /api/brands/unfollow - Unfollow a brand"""
    try:
        user = get_current_user()
        brand_following = BrandFollowing(user.user_folder)

        data = request.get_json()
        brand_id = data.get('brand_id', '')

        if not brand_id:
            return jsonify({
                'success': False,
                'error': 'brand_id is required'
            }), 400

        success, message = brand_following.unfollow_brand(brand_id)

        return jsonify({
            'success': success,
            'message': message
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def check_following():
    """POST /api/brands/check-following - Check if user is following a brand"""
    try:
        user = get_current_user()
        brand_following = BrandFollowing(user.user_folder)

        data = request.get_json()
        brand_id = data.get('brand_id', '')

        if not brand_id:
            return jsonify({
                'success': False,
                'error': 'brand_id is required'
            }), 400

        is_following = brand_following.is_following(brand_id)

        return jsonify({
            'is_following': is_following
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_following_brands():
    """GET /api/brands/following - Get all brands user is following"""
    try:
        user = get_current_user()
        brand_following = BrandFollowing(user.user_folder)

        brands = brand_following.get_following_brands()

        return jsonify({
            'brands': brands,
            'count': len(brands)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def update_brand_notifications():
    """POST /api/brands/notifications - Update notification preferences for a brand"""
    try:
        user = get_current_user()
        brand_following = BrandFollowing(user.user_folder)

        data = request.get_json()
        brand_id = data.get('brand_id', '')
        notify_new_products = data.get('notify_new_products')
        notify_price_changes = data.get('notify_price_changes')

        if not brand_id:
            return jsonify({
                'success': False,
                'error': 'brand_id is required'
            }), 400

        success, message = brand_following.update_notification_preferences(
            brand_id,
            notify_new_products,
            notify_price_changes
        )

        return jsonify({
            'success': success,
            'message': message
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def update_brand_notes():
    """POST /api/brands/notes - Add or update notes for a followed brand"""
    try:
        user = get_current_user()
        brand_following = BrandFollowing(user.user_folder)

        data = request.get_json()
        brand_id = data.get('brand_id', '')
        notes = data.get('notes', '')

        if not brand_id:
            return jsonify({
                'success': False,
                'error': 'brand_id is required'
            }), 400

        success, message = brand_following.add_notes(brand_id, notes)

        return jsonify({
            'success': success,
            'message': message
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def register_brand_following_routes(app):
    """Register all brand following routes (all require authentication)"""
    from functools import wraps
    from backend.auth.user_system.middleware import require_auth

    # Apply auth middleware to all endpoints
    @wraps(follow_brand)
    @require_auth
    def protected_follow_brand():
        return follow_brand()

    @wraps(unfollow_brand)
    @require_auth
    def protected_unfollow_brand():
        return unfollow_brand()

    @wraps(check_following)
    @require_auth
    def protected_check_following():
        return check_following()

    @wraps(get_following_brands)
    @require_auth
    def protected_get_following_brands():
        return get_following_brands()

    @wraps(update_brand_notifications)
    @require_auth
    def protected_update_brand_notifications():
        return update_brand_notifications()

    @wraps(update_brand_notes)
    @require_auth
    def protected_update_brand_notes():
        return update_brand_notes()

    app.add_url_rule('/api/brands/follow', 'follow_brand', protected_follow_brand, methods=['POST'])
    app.add_url_rule('/api/brands/unfollow', 'unfollow_brand', protected_unfollow_brand, methods=['POST'])
    app.add_url_rule('/api/brands/check-following', 'check_following', protected_check_following, methods=['POST'])
    app.add_url_rule('/api/brands/following', 'get_following_brands', protected_get_following_brands, methods=['GET'])
    app.add_url_rule('/api/brands/notifications', 'update_brand_notifications', protected_update_brand_notifications, methods=['POST'])
    app.add_url_rule('/api/brands/notes', 'update_brand_notes', protected_update_brand_notes, methods=['POST'])

    print("✅ Brand Following API routes registered (6 endpoints, all require auth)")
