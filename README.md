# Image Downloader

A configurable and modular Python tool for downloading images from websites. 

## Features

- **Configurable**: JSON config files and CLI arguments
- **Rate Limited**: Respects servers with configurable delays
- **Robust**: Retry logic and error handling
- **Flexible**: Custom CSS selectors and attributes
- **Safe**: Size limits and format filtering
- **Progress Tracking**: Visual feedback during downloads

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
# Download first 5 images from a page
python image_downloader.py "https://example.com" -n 5 -o images/

# With custom delay and size limits
python image_downloader.py "https://example.com" -d 2.0 --min-size 1024 --max-size 1048576
```

### Advanced Usage

```bash
# Use custom CSS selector for specific image types
python image_downloader.py "https://example.com" --selector "img.gallery-image" -n 10

# Download from data attributes instead of src
python image_downloader.py "https://example.com" --selector "img" --attribute "data-src"
```

### Configuration Files

Create a JSON config file:

```bash
# Use example config as template
cp config_example.json my_config.json
# Edit my_config.json with your settings

# Use config file
python image_downloader.py --config my_config.json

# Save current CLI args to config
python image_downloader.py "https://example.com" -n 5 --save-config my_config.json
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `url` | str | required | Target URL to scrape |
| `output_dir` | str | "downloads" | Output directory |
| `max_images` | int | None | Maximum images to download |
| `delay` | float | 1.0 | Delay between requests (seconds) |
| `timeout` | int | 30 | Request timeout |
| `retries` | int | 3 | Number of retry attempts |
| `user_agent` | str | Default UA | Custom user agent |
| `image_formats` | list | ["jpg", "jpeg", "png", "gif", "webp", "bmp"] | Allowed formats |
| `min_size` | int | None | Minimum file size (bytes) |
| `max_size` | int | None | Maximum file size (bytes) |
| `selector` | str | "img" | CSS selector for elements |
| `attribute` | str | "src" | Attribute containing URLs |
| `filename_template` | str | "{index:03d}_{filename}" | Filename format |
| `headers` | dict | {} | Additional HTTP headers |

## Examples

### Gallery Sites
```bash
# Download from image galleries
python image_downloader.py "https://gallery-site.com" --selector "a.image-link" --attribute "href"
```

### Background Images
```bash
# Extract from CSS background-image properties
python image_downloader.py "https://site.com" --selector "div.bg-image" --attribute "data-bg"
```

### High-Resolution Only
```bash
# Only download images larger than 100KB
python image_downloader.py "https://site.com" --min-size 102400 -n 20
```

## Programmatic Usage

```python
from image_downloader import ImageDownloader, DownloadConfig

config = DownloadConfig(
    url="https://example.com",
    max_images=5,
    delay=1.5,
    output_dir="my_images"
)

downloader = ImageDownloader(config)
files = downloader.download_all()
print(f"Downloaded: {files}")
```

## Best Practices

1. **Check robots.txt** before scraping any site
2. **Use appropriate delays** to avoid overloading servers
3. **Respect copyright** - only use for public domain content
4. **Check terms of service** of target websites
5. **Start with small batches** to test selectors
6. **Use size limits** to avoid downloading unwanted files

## Legal Notice

This tool is intended for downloading non-licensed, public domain, or personally owned content only. Users are responsible for ensuring they have proper rights to download any content. Always respect website terms of service and copyright laws.