# Fashion Scraping Pipeline

Staged extraction pipeline with checkpointing between stages.

## Setup

```bash
cd /Users/bhavyajain/Code/fashion_archive/backend
source ../venv/bin/activate
```

## Stages

| Stage | Command | Input | Output |
|-------|---------|-------|--------|
| 1. Navigation | `python pipeline.py nav <url>` | URL | `extractions/{domain}/nav.json`, `nav.txt` |
| 2. URLs | `python pipeline.py urls <domain>` | `nav.json` | `extractions/{domain}/urls.json`, `urls.txt` |
| 3. Products | `python pipeline.py products <domain>` | `urls.json` | `extractions/{domain}/products/`, `config.json` |

## Commands

### Individual Stages

```bash
# Stage 1: Extract navigation tree
python pipeline.py nav https://www.eckhauslatta.com

# Stage 2: Extract product URLs (requires nav.json)
python pipeline.py urls eckhauslatta_com

# Stage 3: Extract product details (requires urls.json)
python pipeline.py products eckhauslatta_com
```

### Combined Stages

```bash
# Stages 1+2: Navigation + URLs
python pipeline.py nav+urls https://www.eckhauslatta.com

# Stages 2+3: URLs + Products
python pipeline.py urls+products eckhauslatta_com

# Full pipeline: All stages
python pipeline.py all https://www.eckhauslatta.com
```

## Output Structure

```
backend/extractions/{domain}/
  nav.json              # Stage 1: Category tree (JSON)
  nav.txt               # Stage 1: Readable version
  urls.json             # Stage 2: Categories + product URLs (JSON)
  urls.txt              # Stage 2: Readable version
  config.json           # Stage 3: Extraction strategy config
  products/             # Stage 3: Product details
    {category}/
      {subcategory}/
        {product-slug}.json
```

## Examples

```bash
# Test navigation only
python pipeline.py nav https://www.eckhauslatta.com
cat extractions/eckhauslatta_com/nav.txt

# Test URLs only (after nav)
python pipeline.py urls eckhauslatta_com
cat extractions/eckhauslatta_com/urls.txt

# Full run on a new brand
python pipeline.py all https://www.khaite.com
```

## Debugging

### Test Single Category (URL Extraction)

Use `test_category.py` to debug URL extraction for a single category page:

```bash
# Basic usage (headful by default - shows browser)
python test_category.py <category_url>

# With expected product count
python test_category.py <url> --target <count>

# Headless mode (no browser window)
python test_category.py <url> --headless
```

**Examples:**

```bash
# Test poolhouse new releases (expect 239 products)
python test_category.py https://poolhousenewyork.com/collections/new-releases --target 239

# Test eckhauslatta bags in headless mode
python test_category.py https://www.eckhauslatta.com/collections/bags --headless

# Quick test without target
python test_category.py https://www.khaite.com/collections/dresses
```

The test shows:
- Pagination element detection
- Scroll progress and element positions
- Load more button detection
- LLM classification results
- Final product count vs target

## Troubleshooting

If a stage fails, you can re-run just that stage. Previous stage outputs are preserved.

```bash
# Re-run failed navigation
python pipeline.py nav https://www.eckhauslatta.com

# Then continue with URLs
python pipeline.py urls eckhauslatta_com
```
