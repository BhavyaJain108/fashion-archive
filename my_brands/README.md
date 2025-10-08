# My Brands - Fashion Brand Monitoring System

This directory contains the complete My Brands system for monitoring and scraping fashion brand websites.

## Directory Structure

```
my_brands/
├── README.md                    # This file
├── __init__.py                  # Package initialization
├── brands_api.py               # Main API for brand operations
├── brands_db.py               # Database operations for brands
├── brands.db                  # SQLite database
├── brand_url_resolver.py      # URL resolution and validation
├── brand_validator.py         # Brand website validation
├── llm_client.py             # LLM integration for intelligent operations
├── integration_example.py    # Example usage
├── INTEGRATION_GUIDE.md      # Integration documentation
├── scraping/                 # 🔧 All scraping methods and strategies
│   ├── __init__.py
│   ├── intelligent_scraper.py    # AI-powered scraping with multiple fallbacks
│   ├── product_scraper.py        # Direct product page scraping
│   ├── scraping_detector.py      # Anti-bot detection and evasion
│   └── scraping_strategies.py    # Various scraping approach implementations
└── agentic_research/         # 🤖 Research and experimental features
    ├── README.md
    ├── ARCHITECTURE.md
    ├── fashion_web_scraper.py
    ├── simple_research_agents.py
    └── demo.py
```

## Core Components

### Main System
- **brands_api.py** - Central API for all brand operations
- **brands_db.py** - Database management and queries
- **brand_url_resolver.py** - Smart URL handling and validation

### Scraping Engine (`scraping/`)
- **intelligent_scraper.py** - Main scraping orchestrator with AI fallbacks
- **scraping_strategies.py** - Multiple scraping approaches (DOM, API, headless)
- **scraping_detector.py** - Anti-detection and stealth capabilities
- **product_scraper.py** - Specialized product page extraction

### Research Framework (`agentic_research/`)
- **simple_research_agents.py** - AI agents for brand discovery
- **fashion_web_scraper.py** - Advanced research scraping
- Experimental features and future development

## Adding New Scraping Methods

To add a new scraping method:

1. **Add to `scraping/scraping_strategies.py`**:
   - Implement your strategy class
   - Follow the existing pattern with `attempt_scrape()` method

2. **Register in `scraping/intelligent_scraper.py`**:
   - Add your strategy to the fallback chain
   - Configure priority and parameters

3. **Test with `integration_example.py`**:
   - Verify your method works with existing brands

## Quick Start

```python
from my_brands.brands_api import MyBrandsAPI

api = MyBrandsAPI()
brands = api.get_brands()
products = api.scrape_brand_products(brand_id=1)
```

See `INTEGRATION_GUIDE.md` for detailed usage examples.