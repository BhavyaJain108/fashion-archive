#!/usr/bin/env python3
"""
User Authentication System
=========================

Simple authentication logic for login/logout/registration.
"""

from typing import Optional, Tuple
from .models import User, UserSession, UserDatabase

class UserAuth:
    """User authentication manager"""
    
    def __init__(self):
        self.db = UserDatabase()
    
    def login(self, username: str, password: str) -> Tuple[bool, Optional[User], Optional[UserSession], str]:
        """
        Attempt user login
        
        Returns:
            (success, user, session, message)
        """
        # Clean up expired sessions
        self.db.cleanup_expired_sessions()
        
        # Check if user exists
        user = self.db.get_user_by_username(username)
        
        if not user:
            return False, None, None, f"User '{username}' not found"
        
        # Verify password
        if not self.db.verify_password(username, password):
            return False, None, None, "Invalid password"
        
        # Create session
        session = self.db.create_session(user.id)
        
        # Update last login
        self.db.update_last_login(user.id)
        
        return True, user, session, "Login successful"
    
    def register(self, username: str, password: str, display_name: str = None) -> Tuple[bool, Optional[User], Optional[UserSession], str]:
        """
        Register a new user
        
        Returns:
            (success, user, session, message)
        """
        # Validate input
        if not username or not password:
            return False, None, None, "Username and password are required"
        
        if len(username) < 3:
            return False, None, None, "Username must be at least 3 characters"
        
        if len(password) < 4:
            return False, None, None, "Password must be at least 4 characters"
        
        # Check if user already exists
        existing_user = self.db.get_user_by_username(username)
        if existing_user:
            return False, None, None, f"User '{username}' already exists"
        
        try:
            # Create user
            user = self.db.create_user(username, password, display_name)
            
            # Create session
            session = self.db.create_session(user.id)
            
            return True, user, session, f"Account created successfully! Welcome {user.display_name}!"
        
        except Exception as e:
            return False, None, None, f"Failed to create account: {str(e)}"
    
    def logout(self, session_token: str) -> bool:
        """Logout user by deleting session"""
        try:
            self.db.delete_session(session_token)
            return True
        except:
            return False
    
    def validate_session(self, session_token: str) -> Tuple[bool, Optional[User], str]:
        """
        Validate session token and return user
        
        Returns:
            (valid, user, message)
        """
        if not session_token:
            return False, None, "No session token provided"
        
        # Get session
        session = self.db.get_session(session_token)
        if not session:
            return False, None, "Invalid session token"
        
        # Check if expired
        if session.is_expired():
            self.db.delete_session(session_token)
            return False, None, "Session expired"
        
        # Get user
        user = self.db.get_user_by_id(session.user_id)
        if not user:
            return False, None, "User not found"
        
        # Update session last used
        self.db.update_session_last_used(session_token)
        
        return True, user, "Session valid"
    
    def get_or_create_user(self, username: str, password: str) -> Tuple[bool, Optional[User], Optional[UserSession], str]:
        """
        Try login first, if fails, offer to create account
        This matches the UX flow you described
        
        Returns:
            (success, user, session, message)
        """
        # First try login
        success, user, session, message = self.login(username, password)
        
        if success:
            return True, user, session, f"Welcome back, {user.display_name}!"
        
        # If user doesn't exist, this is a registration opportunity
        if "not found" in message:
            return False, None, None, f"User '{username}' not found. Would you like to create a new account?"
        
        # If password is wrong, don't offer registration
        return False, None, None, message