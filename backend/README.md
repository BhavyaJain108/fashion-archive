# Backend Directory

This directory contains the organized backend code for the Fashion Archive application.

## Structure

```
backend/
├── app.py                    # Main Flask application entry point
├── api/                      # API endpoints
│   ├── __init__.py
│   └── routes.py            # All 22 premium scraper API routes
├── storage/                  # Data storage layer
│   ├── __init__.py
│   ├── file_manager.py      # File-based storage operations
│   ├── database.py          # Database operations (SQLite/PostgreSQL)
│   ├── storage_layer.py     # Unified storage interface
│   └── schema.sql           # Database schema
├── services/                 # Business logic & integrations
│   ├── __init__.py
│   └── results_writer.py    # Transforms scraper output to storage format
└── scraper/                  # Premium brand scraper
    ├── brand.py              # Main scraping logic
    ├── page_extractor.py     # Product extraction
    ├── llm_handler.py        # LLM integration
    ├── prompts/              # LLM prompts
    └── tests/                # Scraper tests
```

## Usage

### Run the backend server:
```bash
python backend/app.py
```

Or use the legacy entry point (includes all endpoints):
```bash
python clean_api.py
```

### Access API:
```bash
# Health check
curl http://localhost:8081/api/health

# List brands
curl http://localhost:8081/api/brands

# Create a brand
curl -X POST http://localhost:8081/api/brands \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Brand","homepage_url":"https://brand.com"}'
```

## Storage System

The storage layer provides a unified interface that works with:
- **Files**: JSON files in `/data/brands/`
- **Database**: SQLite or PostgreSQL
- **Both**: Dual-write mode

Configure via environment variable:
```bash
export STORAGE_MODE=files      # Default: file-based
export STORAGE_MODE=database   # Use database
export STORAGE_MODE=both       # Write to both
```

## API Endpoints

See `docs/PREMIUM_SCRAPER_INTEGRATION.md` for complete API documentation.

**Summary:**
- 5 Brand endpoints
- 4 Product endpoints
- 2 Classification endpoints
- 2 Attribute endpoints
- 6 Scraping endpoints
- 2 Image endpoints
- **22 total endpoints**

## Integration with Scraper

The scraper (`backend/scraper/`) integrates with the backend via:
- `backend.services.ScrapeResultsWriter` - transforms raw scraper output
- `backend.storage` - stores normalized data

When scraper runs in production mode (`test_mode=False`), it automatically saves results using the new storage system.

## Development

### Adding new endpoints:
1. Add route function in `backend/api/routes.py`
2. Register in `register_routes()` function
3. Update documentation

### Changing storage:
1. Modify `backend/storage/file_manager.py` for file operations
2. Modify `backend/storage/database.py` for database operations
3. The `storage_layer.py` provides the unified interface

## Testing

```bash
# Run integration tests
python tests/test_integration.py

# Test individual components
python -c "from backend.storage import get_storage; s = get_storage(); print('OK')"
```
