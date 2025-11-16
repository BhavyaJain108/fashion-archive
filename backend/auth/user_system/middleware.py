#!/usr/bin/env python3
"""
Authentication Middleware
========================

Flask middleware for protecting API routes with user authentication.
"""

from functools import wraps
from flask import request, jsonify, g
from .auth import UserAuth

# Global auth instance
auth = UserAuth()

def require_auth(f):
    """
    Decorator to protect API routes with authentication
    
    Usage:
        @app.route('/api/protected')
        @require_auth
        def protected_route():
            user = g.current_user
            return jsonify({'message': f'Hello {user.display_name}'})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get session token from Authorization header or query param
        token = None
        
        # Try Authorization header first
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header[7:]  # Remove 'Bearer ' prefix
        
        # Fallback to query parameter
        if not token:
            token = request.args.get('session_token')
        
        # Fallback to JSON body
        if not token and request.is_json:
            token = request.get_json().get('session_token')
        
        if not token:
            return jsonify({
                'error': 'Authentication required', 
                'success': False,
                'code': 'NO_TOKEN'
            }), 401
        
        # Validate session
        valid, user, message = auth.validate_session(token)
        if not valid:
            return jsonify({
                'error': message, 
                'success': False,
                'code': 'INVALID_SESSION'
            }), 401
        
        # Store user in Flask context for use in route
        g.current_user = user
        g.session_token = token
        
        return f(*args, **kwargs)
    
    return decorated_function

def get_current_user():
    """Get current authenticated user from Flask context"""
    return getattr(g, 'current_user', None)

def get_session_token():
    """Get current session token from Flask context"""
    return getattr(g, 'session_token', None)

def optional_auth(f):
    """
    Decorator for routes that work with or without authentication
    Sets g.current_user if valid session is provided, but doesn't require it
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Try to get token (same logic as require_auth)
        token = None
        
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header[7:]
        
        if not token:
            token = request.args.get('session_token')
        
        if not token and request.is_json:
            token = request.get_json().get('session_token')
        
        # If token provided, validate it
        if token:
            valid, user, message = auth.validate_session(token)
            if valid:
                g.current_user = user
                g.session_token = token
            else:
                g.current_user = None
                g.session_token = None
        else:
            g.current_user = None
            g.session_token = None
        
        return f(*args, **kwargs)
    
    return decorated_function