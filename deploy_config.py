#!/usr/bin/env python3
"""
Production Configuration for Deployment
=======================================
"""

import os
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class DeployConfig:
    """Production deployment configuration"""
    
    # Server Configuration - configured for cloud deployment
    HOST = '0.0.0.0'  # Allow external connections
    PORT = int(os.getenv('PORT', 8081))  # Use cloud provider's PORT or default
    DEBUG = False  # Never debug in production
    
    # API Configuration
    BASE_URL = os.getenv('BACKEND_URL', f"http://localhost:{PORT}")
    API_PREFIX = "/api"
    
    # Database Configuration - use environment variables for cloud
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'fashion_archive.db')
    BRANDS_DATABASE_PATH = os.getenv('BRANDS_DATABASE_PATH', 'my_brands/brands.db')
    
    # Storage Configuration  
    BRAND_COLLECTIONS_DIR = os.getenv('BRAND_COLLECTIONS_DIR', 'brand_collections')
    DOWNLOADS_DIR = os.getenv('DOWNLOADS_DIR', 'downloads')
    BRANDS_CACHE_DIR = os.getenv('BRANDS_CACHE_DIR', BRAND_COLLECTIONS_DIR)
    
    # LLM Configuration
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
    LLM_MODEL = os.getenv('LLM_MODEL', 'gpt-4')
    
    # Security
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')
    
    @classmethod
    def get_image_url(cls, relative_path: str) -> str:
        """Generate absolute URL for cached images"""
        return f"{cls.BASE_URL}{cls.API_PREFIX}/brands/image/{relative_path}"
    
    @classmethod
    def to_dict(cls) -> Dict[str, Any]:
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

# Global config instance for deployment
deploy_config = DeployConfig()