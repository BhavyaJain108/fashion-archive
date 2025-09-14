#!/usr/bin/env python3
"""
Configuration Management
=======================

Centralized configuration for the Fashion Archive application.
"""

import os
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(env_path)

class Config:
    """Application configuration"""
    
    # Server Configuration
    HOST = os.getenv('HOST', '127.0.0.1')
    PORT = int(os.getenv('PORT', 8081))
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
    
    # API Configuration
    BASE_URL = f"http://{HOST}:{PORT}"
    API_PREFIX = "/api"
    
    # Database Configuration
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'fashion_archive.db')
    BRANDS_DATABASE_PATH = os.getenv('BRANDS_DATABASE_PATH', 'my_brands/brands.db')
    
    # Cache Configuration
    BRANDS_CACHE_DIR = os.getenv('BRANDS_CACHE_DIR', 'my_brands_cache')
    DOWNLOADS_DIR = os.getenv('DOWNLOADS_DIR', 'downloads')
    
    # LLM Configuration
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    LLM_MODEL = os.getenv('LLM_MODEL', 'gpt-4')
    
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

# Global config instance
config = Config()