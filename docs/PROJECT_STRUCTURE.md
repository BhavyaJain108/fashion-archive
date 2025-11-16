# Fashion Archive - Project Structure

## Directory Organization

```
fashion_archive/
│
├── backend/                          # Backend API & Storage
│   ├── app.py                        # Main Flask application
│   ├── api/                          # REST API endpoints
│   │   ├── routes.py                 # 22 premium scraper endpoints
│   │   └── __init__.py
│   ├── storage/                      # Data storage layer
│   │   ├── file_manager.py           # File operations
│   │   ├── database.py               # Database operations
│   │   ├── storage_layer.py          # Unified interface
│   │   ├── schema.sql                # DB schema
│   │   └── __init__.py
│   ├── services/                     # Business logic
│   │   ├── results_writer.py         # Scraper integration
│   │   └── __init__.py
│   ├── scraper/                      # Premium brand scraper
│   │   ├── brand.py                  # Main scraping logic
│   │   ├── page_extractor.py         # Product extraction
│   │   ├── llm_handler.py            # LLM integration
│   │   ├── modal_bypass_engine.py    # Modal detection & bypass
│   │   ├── prompts/                  # LLM prompts
│   │   ├── tests/                    # Scraper tests
│   │   │   ├── test_04_full_pipeline.py
│   │   │   └── results/              # Test output
│   │   └── api/                      # Legacy API (deprecated)
│   │       └── premium_api.py
│   └── README.md                     # Backend documentation
│
├── web_ui/                           # Frontend (React/Electron)
│   ├── src/
│   │   ├── App.js                    # Main app component
│   │   ├── components/               # UI components
│   │   │   ├── MyBrandsPanel.js      # Brand management UI
│   │   │   └── ...
│   │   └── services/
│   │       └── api.js                # API client
│   ├── public/
│   └── package.json
│
├── data/                             # Data storage (gitignored)
│   ├── brands/                       # Per-brand data
│   │   └── {brand_slug}/
│   │       ├── brand.json            # Brand metadata
│   │       ├── products.json         # Product catalog
│   │       ├── navigation.json       # Category tree
│   │       ├── scraping_intel.json   # Scraping patterns
│   │       ├── images/               # Product images
│   │       └── scrape_runs/          # Historical runs
│   └── indexes/
│       └── brands.json               # Global brand index
│
├── tests/                            # Integration tests
│   └── test_integration.py           # End-to-end tests
│
├── docs/                             # Documentation
│   └── PREMIUM_SCRAPER_INTEGRATION.md  # Complete spec & API docs
│
├── user_system/                      # User authentication
│   ├── auth.py                       # User auth logic
│   └── middleware.py                 # Auth middleware
│
├── clean_api.py                      # Legacy API entry point
├── config.py                         # Application configuration
├── requirements.txt                  # Python dependencies
└── README.md                         # Project overview
```

## Key Components

### 1. Backend (`backend/`)
Organized, professional backend structure:
- **API Layer**: REST endpoints for frontend
- **Storage Layer**: File + Database with unified interface
- **Services**: Business logic and scraper integration

### 2. Scraper (`backend/scraper/`)
Premium brand scraping engine:
- Autonomous navigation tree analysis
- Pattern discovery and reuse
- Multi-page extraction
- LLM-powered intelligence

### 3. Frontend (`web_ui/`)
React-based UI (Electron app):
- Brand management
- Product browsing
- Image viewing
- Scraping controls

### 4. Data (`data/`)
Structured storage:
- JSON files for flexibility
- Optional SQLite/PostgreSQL database
- Organized by brand
- Historical run tracking

## Data Flow

```
Frontend (web_ui)
    ↓ HTTP Request
Backend API (backend/api/routes.py)
    ↓ Uses
Storage Layer (backend/storage/storage_layer.py)
    ↓ Reads/Writes
File Storage (data/) ← → Database (SQLite)
    ↑ Populated by
Scraper (backend/scraper/brand.py)
    ↓ Transforms via
Results Writer (backend/services/results_writer.py)
```

## Getting Started

### 1. Install Dependencies
```bash
pip install -r requirements.txt
cd web_ui && npm install
```

### 2. Run Backend
```bash
# Option A: New organized backend
python backend/app.py

# Option B: Legacy (includes all endpoints)
python clean_api.py
```

### 3. Run Frontend
```bash
cd web_ui
npm start
```

### 4. Test Scraper
```bash
# Test mode (saves to backend/scraper/tests/results/)
python backend/scraper/tests/test_04_full_pipeline.py

# Production mode (saves to data/brands/)
# Use API: POST /api/brands/{id}/scrape
```

## Configuration

### Storage Mode
Set via environment variable:
```bash
export STORAGE_MODE=files      # File-based (default)
export STORAGE_MODE=database   # Database only
export STORAGE_MODE=both       # Dual-write
```

### API Server
Edit `config.py`:
```python
HOST = "localhost"
PORT = 8081
DEBUG = True
```

## API Documentation

See `docs/PREMIUM_SCRAPER_INTEGRATION.md` for:
- Complete API specification
- Request/response formats
- Query examples
- Database schema
- Storage architecture

## Development Workflow

### Adding a new brand:
1. `POST /api/brands` with name and URL
2. `POST /api/brands/{id}/scrape` to scrape
3. `GET /api/products?brand_id={id}` to query products

### Querying products:
```bash
# All products for a brand
GET /api/products?brand_id=jukuhara

# Filter by category
GET /api/products?brand_id=jukuhara&classification_url=https://...

# Search
GET /api/products/search?q=hoodie&brand_id=jukuhara

# Aggregate by category
GET /api/products/aggregate?brand_id=jukuhara&group_by=classification.category.name
```

## Migration Notes

### Old vs New Structure

**Old (deprecated):**
- `data_manager.py` (root)
- `unified_api.py` (root)
- `/api/premium/*` endpoints

**New (current):**
- `backend/storage/file_manager.py`
- `backend/api/routes.py`
- `/api/brands/*`, `/api/products/*` endpoints

The old files have been moved and organized. `clean_api.py` still works and includes both old and new endpoints for backwards compatibility.

## Testing

```bash
# Integration tests
python tests/test_integration.py

# Storage layer
python -c "from backend.storage import get_storage; s = get_storage(); print('OK')"

# API (requires server running)
curl http://localhost:8081/api/health
```

## Contributing

When adding new features:
1. Backend code → `backend/`
2. Scraper code → `scraper_premium/`
3. Frontend code → `web_ui/src/`
4. Tests → `tests/`
5. Documentation → `docs/`

Keep the organization clean and professional!
