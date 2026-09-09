#!/usr/bin/env python3
"""
Configuration Management
=======================

Centralized configuration for the Fashion Archive application.
"""

import os
from typing import Any

from dotenv import load_dotenv

# Load environment variables from .env file
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(env_path)

class Config:
    """Application configuration"""
    
    # Server Configuration
    # HOST defaults to 0.0.0.0 because a hosted container must accept traffic
    # from outside itself; on 127.0.0.1 the platform health check can never
    # connect and the deploy fails.
    HOST = os.getenv('HOST', '0.0.0.0')
    PORT = int(os.getenv('PORT', 8081))
    # DEBUG defaults to False. It used to default to True, which serves the
    # Werkzeug debugger — an interactive Python console — to anyone who can
    # trigger a traceback. That is remote code execution on a public URL.
    DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

    # Auth / hosting
    DATABASE_URL = os.getenv('DATABASE_URL')
    APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:3000')
    API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:8081')

    # Empty in development: a Domain attribute cannot be set for "localhost",
    # and omitting it makes the cookie host-only, which is what we want there.
    COOKIE_DOMAIN = os.getenv('COOKIE_DOMAIN', '')
    # Secure cookies are not sent over plain http, so local development needs
    # this off. It must be on anywhere real.
    COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'

    # Email (Resend). Without an API key the app falls back to printing
    # verification links to stdout, so local signup works with no credentials.
    RESEND_API_KEY = os.getenv('RESEND_API_KEY')
    MAIL_FROM = os.getenv('MAIL_FROM', 'no-reply@localhost')
    
    # API Configuration
    BASE_URL = f"http://{HOST}:{PORT}"
    API_PREFIX = "/api"
    
    # Database Configuration
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'fashion_archive.db')
    BRANDS_DATABASE_PATH = os.getenv('BRANDS_DATABASE_PATH', 'my_brands/brands.db')
    
    # Storage Configuration  
    BRAND_COLLECTIONS_DIR = os.getenv('BRAND_COLLECTIONS_DIR', 'brand_collections')
    DOWNLOADS_DIR = os.getenv('DOWNLOADS_DIR', 'downloads')
    # Legacy cache directory (deprecated - use BRAND_COLLECTIONS_DIR)
    BRANDS_CACHE_DIR = os.getenv('BRANDS_CACHE_DIR', BRAND_COLLECTIONS_DIR)
    
    # LLM Configuration
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    LLM_MODEL = os.getenv('LLM_MODEL', 'gpt-4')
    
    @classmethod
    def get_image_url(cls, relative_path: str) -> str:
        """Generate absolute URL for cached images"""
        return f"{cls.BASE_URL}{cls.API_PREFIX}/brands/image/{relative_path}"
    
    @classmethod
    def to_dict(cls) -> dict[str, Any]:
        """Export configuration as dictionary"""
        return {
            'host': cls.HOST,
            'port': cls.PORT,
            'debug': cls.DEBUG,
            'base_url': cls.BASE_URL,
            'database_path': cls.DATABASE_PATH,
            'brands_database_path': cls.BRANDS_DATABASE_PATH,
            'brands_cache_dir': cls.BRANDS_CACHE_DIR,
            'downloads_dir': cls.DOWNLOADS_DIR
        }

# Global config instance
config = Config()