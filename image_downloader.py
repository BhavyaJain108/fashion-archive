#!/usr/bin/env python3
"""
Configurable Image Downloader
A modular tool for downloading images from websites (for non-licensed/public domain content only).
"""

import os
import re
import time
import json
import argparse
from pathlib import Path
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from collection_organizer import CollectionOrganizer
    ORGANIZER_AVAILABLE = True
except ImportError:
    ORGANIZER_AVAILABLE = False


@dataclass
class DownloadConfig:
    """Configuration class for the image downloader."""
    url: str
    output_dir: str = "downloads"
    max_images: Optional[int] = None
    delay: float = 1.0
    timeout: int = 30
    retries: int = 3
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    image_formats: List[str] = None
    min_size: Optional[int] = None
    max_size: Optional[int] = None
    selector: str = "img"
    attribute: str = "src"
    filename_template: str = "{filename}"
    headers: Dict[str, str] = None
    url_collection_info: Dict[str, str] = None
    
    def __post_init__(self):
        if self.image_formats is None:
            self.image_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
        if self.headers is None:
            self.headers = {
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
        self.headers.setdefault('User-Agent', self.user_agent)
        if self.url_collection_info is None:
            self.url_collection_info = self._extract_collection_info_from_url(self.url)
    
    def _extract_collection_info_from_url(self, url: str) -> Dict[str, str]:
        """Extract collection name from URL path."""
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        # Remove trailing slash and get the collection name
        collection_name = path.split('/')[-1] if path else ''
        
        return {'collection_name': collection_name}


class ImageDownloader:
    """Main image downloader class."""
    
    def __init__(self, config: DownloadConfig):
        self.config = config
        self.session = self._create_session()
        self.downloaded_count = 0
        self.download_lock = Lock()
        
    def _create_session(self) -> requests.Session:
        """Create a configured requests session with retry strategy."""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=self.config.retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(self.config.headers)
        
        return session
    
    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch and parse a web page."""
        try:
            print(f"Fetching page: {url}")
            response = self.session.get(url, timeout=self.config.timeout)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"Error fetching page: {e}")
            return None
    
    def extract_image_urls(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract image URLs from parsed HTML."""
        image_urls = []
        elements = soup.select(self.config.selector)
        
        for element in elements:
            img_url = element.get(self.config.attribute)
            if img_url:
                # Convert relative URLs to absolute
                full_url = urljoin(base_url, img_url)
                if self._is_valid_image_url(full_url):
                    image_urls.append(full_url)
        
        return image_urls
    
    def _is_valid_image_url(self, url: str) -> bool:
        """Check if URL points to a valid image format."""
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        
        # Check file extension
        for fmt in self.config.image_formats:
            if path_lower.endswith(f'.{fmt}'):
                return True
        
        # Check query parameters for image formats
        query_lower = parsed.query.lower()
        return any(fmt in query_lower for fmt in self.config.image_formats)
    
    def download_image(self, url: str, filepath: Path) -> bool:
        """Download a single image."""
        try:
            print(f"Downloading: {url}")
            response = self.session.get(url, timeout=self.config.timeout, stream=True)
            response.raise_for_status()
            
            # Check content length if size limits are set
            content_length = response.headers.get('content-length')
            if content_length:
                size = int(content_length)
                if self.config.min_size and size < self.config.min_size:
                    print(f"Skipping {url}: too small ({size} bytes)")
                    return False
                if self.config.max_size and size > self.config.max_size:
                    print(f"Skipping {url}: too large ({size} bytes)")
                    return False
            
            # Save the image
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"Saved: {filepath}")
            return True
            
        except requests.RequestException as e:
            print(f"Error downloading {url}: {e}")
            return False
    
    def generate_filename(self, url: str, index: int) -> str:
        """Generate filename for downloaded image."""
        parsed = urlparse(url)
        original_filename = os.path.basename(parsed.path) or f"image_{index}"
        
        # Remove query parameters from filename
        original_filename = original_filename.split('?')[0]
        
        # Ensure it has an extension
        if '.' not in original_filename:
            original_filename += '.jpg'
        
        # Clean filename
        original_filename = re.sub(r'[^\w\-_\.]', '_', original_filename)
        
        return self.config.filename_template.format(
            index=index,
            filename=original_filename
        )
    
    def download_all(self) -> List[str]:
        """Download all images from the configured URL using parallel processing."""
        # Clean up existing downloads folder first
        output_dir = Path(self.config.output_dir)
        if output_dir.exists():
            import shutil
            print(f"Removing existing downloads folder: {output_dir}")
            shutil.rmtree(output_dir)
        
        # Create fresh downloads folder
        output_dir.mkdir(parents=True, exist_ok=True)
        
        soup = self.fetch_page(self.config.url)
        if not soup:
            return []
        
        image_urls = self.extract_image_urls(soup, self.config.url)
        print(f"Found {len(image_urls)} images")
        
        if self.config.max_images:
            image_urls = image_urls[:self.config.max_images]
            print(f"Limited to first {self.config.max_images} images")
        
        # Determine number of threads (up to 20 based on image count)
        num_threads = min(len(image_urls), 20)
        print(f"Using {num_threads} parallel threads for downloading")
        
        # Create list of download tasks
        download_tasks = []
        for i, url in enumerate(image_urls, 1):
            filename = self.generate_filename(url, i)
            filepath = output_dir / filename
            download_tasks.append((url, filepath, i))
        
        # Download images in parallel
        downloaded_files = []
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            # Submit all download tasks
            future_to_task = {
                executor.submit(self._download_single_image, task): task 
                for task in download_tasks
            }
            
            # Process completed downloads
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                url, filepath, index = task
                
                try:
                    success = future.result()
                    if success:
                        downloaded_files.append(str(filepath))
                        with self.download_lock:
                            self.downloaded_count += 1
                            print(f"Downloaded ({self.downloaded_count}/{len(image_urls)}): {filepath.name}")
                except Exception as e:
                    print(f"Error downloading {url}: {e}")
        
        print(f"Downloaded {len(downloaded_files)} images to {output_dir}")
        return downloaded_files
    
    def _download_single_image(self, task) -> bool:
        """Download a single image (for use in parallel processing)."""
        url, filepath, index = task
        
        # Apply delay for rate limiting (except for first batch)
        if index > 20:  # Only delay after first batch of 20
            time.sleep(self.config.delay)
        
        return self.download_image(url, filepath)


def load_config_from_file(filepath: str) -> DownloadConfig:
    """Load configuration from JSON file."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    return DownloadConfig(**data)


def save_config_to_file(config: DownloadConfig, filepath: str):
    """Save configuration to JSON file."""
    with open(filepath, 'w') as f:
        json.dump(asdict(config), f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Download images from websites")
    parser.add_argument("url", help="URL to download images from")
    parser.add_argument("-o", "--output", default="downloads", help="Output directory")
    parser.add_argument("-n", "--max-images", type=int, help="Maximum number of images")
    parser.add_argument("-d", "--delay", type=float, default=1.0, help="Delay between downloads")
    parser.add_argument("-t", "--timeout", type=int, default=30, help="Request timeout")
    parser.add_argument("--min-size", type=int, help="Minimum image size in bytes")
    parser.add_argument("--max-size", type=int, help="Maximum image size in bytes")
    parser.add_argument("--selector", default="img", help="CSS selector for image elements")
    parser.add_argument("--attribute", default="src", help="Attribute to extract URLs from")
    parser.add_argument("--config", help="Load configuration from JSON file")
    parser.add_argument("--save-config", help="Save current configuration to JSON file")
    parser.add_argument("-f", "--organize", action="store_true", help="Automatically organize collection after download using URL-derived folder name")
    
    args = parser.parse_args()
    
    if args.config:
        config = load_config_from_file(args.config)
        # Override with command line arguments
        if args.url:
            config.url = args.url
    else:
        config = DownloadConfig(
            url=args.url,
            output_dir=args.output,
            max_images=args.max_images,
            delay=args.delay,
            timeout=args.timeout,
            min_size=args.min_size,
            max_size=args.max_size,
            selector=args.selector,
            attribute=args.attribute
        )
    
    if args.save_config:
        save_config_to_file(config, args.save_config)
        print(f"Configuration saved to {args.save_config}")
        return
    
    downloader = ImageDownloader(config)
    downloaded_files = downloader.download_all()
    
    if downloaded_files:
        print("\nDownloaded files:")
        for file in downloaded_files:
            print(f"  {file}")
        
        # Organize collection if requested
        if args.organize:
            if not ORGANIZER_AVAILABLE:
                print("\nWarning: Collection organizer not available. Install collection_organizer.py to use -f flag.")
            else:
                print("\nOrganizing collection...")
                organizer = CollectionOrganizer(config.output_dir)
                
                # Pass URL collection info to organizer if available
                if config.url_collection_info and any(config.url_collection_info.values()):
                    print(f"Using URL collection info: {config.url_collection_info}")
                    result = organizer.organize_folder_with_target_collection(
                        config.url_collection_info, dry_run=False
                    )
                else:
                    result = organizer.organize_folder(dry_run=False)
                
                if 'error' in result:
                    print(f"Organization failed: {result['error']}")
                    if 'total_files' in result:
                        print(f"Try adjusting thresholds: {result['total_files']} files found")
                else:
                    # Handle both URL-based and auto-detected organization
                    if 'target_collection' in result:
                        collection_name = result['target_collection'].get('collection_name', 'Unknown')
                        print(f"✓ Organized as: {collection_name}")
                    elif 'main_collection' in result:
                        print(f"✓ Organized as: {result['main_collection']}")
                    
                    print(f"✓ Kept {result['keeping_files']} files, removed {result['removing_files']}")
                    
                    # Folder name is automatically derived from URL
                    if result.get('renamed'):
                        print(f"✓ Renamed folder to: {Path(result['new_folder']).name}")


if __name__ == "__main__":
    main()