"""
Authentication API Routes
=========================

Endpoints for user authentication and session management
"""

from flask import jsonify, request

# Import user system components
from backend.auth.user_system.auth import UserAuth
from backend.auth.user_system.middleware import require_auth, get_current_user

# Initialize auth system
user_auth = UserAuth()


def auth_login():
    """POST /api/auth/login - Login or register user"""
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


def auth_logout():
    """POST /api/auth/logout - Logout user by invalidating session"""
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


def auth_me():
    """GET /api/auth/me - Get current user profile (requires authentication)"""
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


def auth_validate():
    """POST /api/auth/validate - Validate session token"""
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


def register_auth_routes(app):
    """Register all authentication routes"""

    app.add_url_rule('/api/auth/login', 'auth_login', auth_login, methods=['POST'])
    app.add_url_rule('/api/auth/logout', 'auth_logout', auth_logout, methods=['POST'])
    app.add_url_rule('/api/auth/validate', 'auth_validate', auth_validate, methods=['POST'])

    # Apply auth middleware to protected route
    from functools import wraps

    @wraps(auth_me)
    @require_auth
    def protected_auth_me():
        return auth_me()

    app.add_url_rule('/api/auth/me', 'auth_me', protected_auth_me, methods=['GET'])

    print("✅ Authentication API routes registered (4 endpoints)")
