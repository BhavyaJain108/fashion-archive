"""
Favicon Downloader
==================

Utility to download and store brand favicons for folder icons.
"""

import requests
import os
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from pathlib import Path


class FaviconDownloader:
    """Downloads and stores favicons for brands"""

    @staticmethod
    def download_favicon(homepage_url: str, brand_id: str, save_dir: str = None) -> str:
        """
        Download favicon from a brand's homepage.

        Args:
            homepage_url: The brand's homepage URL
            brand_id: Unique brand identifier
            save_dir: Directory to save favicon (default: data/brands/{brand_id})

        Returns:
            str: Path to downloaded favicon, or None if not found
        """
        try:
            # Set save directory
            if save_dir is None:
                save_dir = os.path.join('data', 'brands', brand_id)

            os.makedirs(save_dir, exist_ok=True)

            # Common favicon locations to try
            favicon_urls = FaviconDownloader._get_favicon_urls(homepage_url)

            # Try each URL until one works
            for favicon_url in favicon_urls:
                try:
                    print(f"      🔍 Trying favicon: {favicon_url}")
                    response = requests.get(favicon_url, timeout=10, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })

                    if response.status_code == 200 and len(response.content) > 0:
                        # Determine file extension from content type
                        content_type = response.headers.get('content-type', '')
                        extension = FaviconDownloader._get_extension_from_content_type(content_type)

                        # Save favicon
                        favicon_path = os.path.join(save_dir, f'favicon{extension}')
                        with open(favicon_path, 'wb') as f:
                            f.write(response.content)

                        print(f"      ✅ Favicon downloaded: {favicon_path}")
                        return favicon_path

                except Exception as e:
                    print(f"      ⚠️  Failed to download from {favicon_url}: {e}")
                    continue

            print(f"      ℹ️  No favicon found for {homepage_url}")
            return None

        except Exception as e:
            print(f"      ❌ Favicon download error: {e}")
            return None

    @staticmethod
    def _get_favicon_urls(homepage_url: str) -> list:
        """
        Get potential favicon URLs to try.

        Returns list of URLs in order of priority.
        """
        parsed = urlparse(homepage_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        favicon_urls = []

        # Try parsing HTML for favicon links
        try:
            response = requests.get(homepage_url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })

            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')

                # Look for link tags with rel="icon" or rel="shortcut icon"
                icon_links = soup.find_all('link', rel=lambda x: x and 'icon' in x.lower() if x else False)

                for link in icon_links:
                    href = link.get('href')
                    if href:
                        # Make absolute URL
                        absolute_url = urljoin(base_url, href)
                        favicon_urls.append(absolute_url)

        except Exception as e:
            print(f"      ⚠️  Could not parse HTML for favicon: {e}")

        # Add common fallback locations
        favicon_urls.extend([
            f"{base_url}/favicon.ico",
            f"{base_url}/favicon.png",
            f"{base_url}/apple-touch-icon.png",
            f"{base_url}/apple-touch-icon-precomposed.png",
        ])

        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for url in favicon_urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return unique_urls

    @staticmethod
    def _get_extension_from_content_type(content_type: str) -> str:
        """Get file extension from content type"""
        content_type = content_type.lower()

        if 'png' in content_type:
            return '.png'
        elif 'jpeg' in content_type or 'jpg' in content_type:
            return '.jpg'
        elif 'svg' in content_type:
            return '.svg'
        elif 'gif' in content_type:
            return '.gif'
        elif 'webp' in content_type:
            return '.webp'
        else:
            return '.ico'  # Default to .ico
