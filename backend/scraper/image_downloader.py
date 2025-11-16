"""
Image Downloader Module
=======================

Downloads product images and saves them with organized file structure.
"""

import os
import requests
import hashlib
from urllib.parse import urlparse
from pathlib import Path
import time

class ImageDownloader:
    """Downloads and manages product images"""
    
    def __init__(self, base_dir: str = "results"):
        """
        Initialize image downloader
        
        Args:
            base_dir: Base directory for saving images
        """
        self.base_dir = Path(base_dir)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def download_image(self, image_url: str, product_name: str, brand_dir: str) -> tuple:
        """
        Download a single image
        
        Args:
            image_url: URL of the image to download
            product_name: Name of the product (for filename)
            brand_dir: Brand directory path
            
        Returns:
            Tuple of (success: bool, local_path: str, error: str)
        """
        if not image_url or not image_url.startswith('http'):
            return False, "", "Invalid image URL"
        
        try:
            # Create brand directory
            brand_path = self.base_dir / brand_dir / "images"
            brand_path.mkdir(parents=True, exist_ok=True)
            
            # Get file extension from URL
            parsed_url = urlparse(image_url)
            ext = os.path.splitext(parsed_url.path)[1]
            if not ext:
                ext = '.jpg'  # Default extension
            
            # Create safe filename
            safe_name = self._create_safe_filename(product_name)
            
            # Add hash to avoid duplicates
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:8]
            filename = f"{safe_name}_{url_hash}{ext}"
            
            local_path = brand_path / filename
            
            # Skip if already exists
            if local_path.exists():
                return True, str(local_path), ""
            
            # Download image
            response = self.session.get(image_url, timeout=10, stream=True)
            response.raise_for_status()
            
            # Save image
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True, str(local_path), ""
            
        except requests.RequestException as e:
            return False, "", f"Download error: {str(e)}"
        except Exception as e:
            return False, "", f"Unexpected error: {str(e)}"
    
    def _create_safe_filename(self, name: str) -> str:
        """Create a safe filename from product name"""
        # Remove/replace unsafe characters
        safe_name = name.replace('/', '_').replace('\\', '_')
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c in ' -_.')
        safe_name = safe_name.strip()
        
        # Limit length
        if len(safe_name) > 50:
            safe_name = safe_name[:50]
        
        # Ensure not empty
        if not safe_name:
            safe_name = "unknown_product"
        
        return safe_name
    
    def batch_download(self, products: list, brand_name: str) -> dict:
        """
        Download images for a batch of products
        
        Args:
            products: List of Product objects
            brand_name: Name of the brand
            
        Returns:
            Dict with download statistics
        """
        stats = {
            "total": len(products),
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "errors": []
        }
        
        print(f"   📸 Downloading {len(products)} images for {brand_name}...")
        
        for i, product in enumerate(products, 1):
            if not product.image:
                stats["skipped"] += 1
                continue
            
            success, local_path, error = self.download_image(
                product.image, 
                product.name, 
                brand_name.lower().replace(' ', '_')
            )
            
            if success:
                stats["success"] += 1
                # Store local path in product metadata
                product.metadata['local_image_path'] = local_path
                if i % 5 == 0:  # Progress update every 5 downloads
                    print(f"      Downloaded {i}/{len(products)} images...")
            else:
                stats["failed"] += 1
                stats["errors"].append(f"{product.name}: {error}")
        
        return stats