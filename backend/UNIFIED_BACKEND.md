
# Unified Backend API - Complete Guide

**Date:** 2025-11-16
**Status:** ✅ Production Ready
**Port:** 8081
**Launch:** `python backend/app.py` or `./run_modern_ui.sh`

---

## Overview

The Fashion Archive now has a single unified backend that serves all functionality:
- ✅ **Premium Scraper API** (22 endpoints) - Brand & product management
- ✅ **High Fashion API** (7 endpoints) - Seasons, collections, images, videos
- ✅ **Favorites API** (6 endpoints) - Favorite looks management
- ✅ **Authentication API** (4 endpoints) - User login & sessions

**Total: ~39 endpoints**

---

## Architecture

### File Structure
```
backend/
├── app.py                          # Main application (unified entry point)
├── api/
│   ├── __init__.py
│   ├── routes.py                   # Premium Scraper API (22 endpoints)
│   ├── high_fashion_routes.py     # High Fashion API (7 endpoints)
│   ├── favorites_routes.py         # Favorites API (6 endpoints)
│   └── auth_routes.py              # Authentication API (4 endpoints)
├── storage/                        # Data layer
├── services/                       # Business logic
└── scraper/                        # Scraping engine
```

### Module Organization

**backend/api/routes.py** - Premium Scraper (Brands & Products)
- Brand CRUD operations
- Product queries with filters
- Classifications discovery
- Attributes discovery
- Scraping job management
- Image serving

**backend/api/high_fashion_routes.py** - High Fashion (nowfashion.com)
- Seasons listing
- Collections by season
- Images download
- Video download/streaming
- Cache management

**backend/api/favorites_routes.py** - Favorites
- Add/remove/view favorite looks
- Check if look is favorited
- Statistics
- Cleanup orphaned images

**backend/api/auth_routes.py** - Authentication
- Login/logout
- Session validation
- User profile
- Registration

---

## API Groups

### 1. Premium Scraper API (22 endpoints)

#### Brands
- `GET /api/brands` - List all brands with pagination
- `GET /api/brands/{id}` - Get brand details
- `POST /api/brands` - Create new brand
- `PUT /api/brands/{id}` - Update brand
- `DELETE /api/brands/{id}` - Delete brand

#### Products
- `GET /api/products` - Query products with filters
  - Query params: `brand_id`, `search`, `classification_url`, `attribute.{key}`, etc.
- `GET /api/products/{url}` - Get single product by URL
- `GET /api/products/aggregate` - Aggregate products by field
- `GET /api/products/search` - Full-text search

#### Classifications
- `GET /api/brands/{id}/classifications` - Get all classifications
- `GET /api/brands/{id}/categories/hierarchy` - Get category tree

#### Attributes
- `GET /api/brands/{id}/attributes` - Discover product attributes
- `GET /api/brands/{id}/attributes/{key}/values` - Get attribute values

#### Scraping
- `POST /api/brands/{id}/scrape` - Start scraping job
- `GET /api/brands/{id}/scrape/status` - Get scrape status
- `GET /api/brands/{id}/scrape/history` - Get scrape run history
- `GET /api/brands/{id}/scraping-intelligence` - Get learned patterns
- `POST /api/brands/analyze` - Analyze if brand is scrapable

#### Images
- `GET /api/images/{brand}/{category}/{file}` - Serve brand image
- `GET /api/products/{url}/images` - Get product images with local URLs

---

### 2. High Fashion API (7 endpoints)

Scrapes nowfashion.com for runway shows.

- `POST /api/seasons` - Get all fashion seasons
- `POST /api/collections` - Get collections for a season
- `POST /api/download-images` - Download images from collection
- `POST /api/download-video` - Download video from collection
- `GET /api/image?path={path}` - Serve cached fashion image
- `GET /api/video?path={path}` - Serve cached video
- `POST /api/cleanup` - Clear cache directories

---

### 3. Favorites API (6 endpoints)

Manage favorite high-fashion looks.

- `GET /api/favourites` - Get all favorite looks
- `POST /api/favourites` - Add look to favorites
- `DELETE /api/favourites` - Remove look from favorites
- `POST /api/favourites/check` - Check if look is favorited
- `GET /api/favourites/stats` - Get favorites statistics
- `POST /api/favourites/cleanup` - Cleanup orphaned images

---

### 4. Authentication API (4 endpoints)

User management and session authentication.

- `POST /api/auth/login` - Login or register user
- `POST /api/auth/logout` - Logout user
- `POST /api/auth/validate` - Validate session token
- `GET /api/auth/me` - Get current user profile (requires auth)

---

## Migration from clean_api.py

### What Changed

**OLD (clean_api.py):**
- Monolithic file with mixed concerns
- Only had high-fashion, favorites, and auth
- Missing brand/product management endpoints
- 900+ lines in one file

**NEW (backend/app.py + modules):**
- Modular architecture with separate route files
- All 4 API groups unified
- Clean separation of concerns
- ~100 lines per module

### Migrated Endpoints

All endpoints from `clean_api.py` have been migrated:

| Old (clean_api.py) | New (backend/) | Status |
|-------------------|----------------|--------|
| `/api/seasons` | `backend/api/high_fashion_routes.py` | ✅ Migrated |
| `/api/collections` | `backend/api/high_fashion_routes.py` | ✅ Migrated |
| `/api/download-images` | `backend/api/high_fashion_routes.py` | ✅ Migrated |
| `/api/download-video` | `backend/api/high_fashion_routes.py` | ✅ Migrated |
| `/api/image` | `backend/api/high_fashion_routes.py` | ✅ Migrated |
| `/api/video` | `backend/api/high_fashion_routes.py` | ✅ Migrated |
| `/api/cleanup` | `backend/api/high_fashion_routes.py` | ✅ Migrated |
| `/api/favourites` (all) | `backend/api/favorites_routes.py` | ✅ Migrated |
| `/api/auth/*` (all) | `backend/api/auth_routes.py` | ✅ Migrated |
| N/A | `backend/api/routes.py` | ✅ New (22 endpoints) |

---

## Frontend Integration

### Existing Pages

**High Fashion** (SeasonsPanel, CollectionsPanel, ImageViewerPanel)
- ✅ No changes needed
- Uses: `/api/seasons`, `/api/collections`, `/api/download-images`, `/api/image`, `/api/video`

**Favorites** (FavouritesPanel)
- ✅ No changes needed
- Uses: `/api/favourites/*`

**Authentication** (LoginModal)
- ✅ No changes needed
- Uses: `/api/auth/*`

**My Brands** (MyBrandsPanel)
- ❌ **NEEDS COMPLETE REBUILD**
- Old implementation expects non-existent endpoints
- Should use new Premium Scraper API (22 endpoints)

### API Base URL

Frontend connects via:
```javascript
// web_ui/src/services/api.js
static BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8081';
```

No changes needed - still uses port 8081.

---

## Running the System

### Option 1: Unified Launcher (Recommended)
```bash
./run_modern_ui.sh
```

This will:
1. Start `backend/app.py` on port 8081
2. Start React dev server on port 3000
3. Frontend automatically connects to backend

### Option 2: Manual
```bash
# Terminal 1: Backend
python backend/app.py

# Terminal 2: Frontend
cd web_ui
npm run dev-react
```

### Verification

```bash
# Test health
curl http://localhost:8081/api/health

# Test brands
curl http://localhost:8081/api/brands

# Test high fashion
curl -X POST http://localhost:8081/api/seasons

# Test favorites
curl http://localhost:8081/api/favourites
```

---

## Dependencies

### Python (backend/app.py)
- Flask
- Flask-CORS
- BeautifulSoup4
- Requests
- Playwright (for scraping)
- favourites_db (local module)
- user_system (local module)

### React (web_ui/)
- React 18.2.0
- No changes to frontend dependencies needed

---

## Next Steps

### Phase 1: My Brands Rebuild ✅ READY
The unified backend is complete and tested. Now rebuild the My Brands frontend page:

1. **Delete old MyBrandsPanel.js** (1,125 lines of outdated code)
2. **Clean up api.js** (remove old brand methods)
3. **Create new MyBrandsPanel.js** using Premium Scraper API

### Phase 2: Enhanced Features (Future)
- Real-time scraping progress with SSE
- Advanced product filtering UI
- Bulk brand operations
- Scraping intelligence visualization

---

## Testing Status

| API Group | Endpoints | Status | Notes |
|-----------|-----------|--------|-------|
| Premium Scraper | 22 | ✅ Tested | All endpoints working |
| High Fashion | 7 | ✅ Tested | Migrated from clean_api.py |
| Favorites | 6 | ✅ Tested | Migrated from clean_api.py |
| Authentication | 4 | ✅ Tested | Migrated from clean_api.py |

**Test Log:** `logs/api_demo_test.log` (268 lines)
**Test Summary:** `logs/api_test_summary.md`

---

## Troubleshooting

### Port 8081 Already in Use
```bash
# Kill all processes on port 8081
lsof -ti:8081 | xargs kill -9

# Then restart
python backend/app.py
```

### Module Import Errors
Make sure you're in the project root:
```bash
cd /Users/bhavyajain/Code/fashion_archive
python backend/app.py
```

### Frontend Can't Connect
1. Check backend is running: `curl http://localhost:8081/api/health`
2. Check frontend API URL in `web_ui/src/services/api.js`
3. Check CORS is enabled (Flask-CORS installed)

---

## File Locations Reference

**Backend:**
- Main app: `/Users/bhavyajain/Code/fashion_archive/backend/app.py`
- Premium API: `/Users/bhavyajain/Code/fashion_archive/backend/api/routes.py`
- High Fashion API: `/Users/bhavyajain/Code/fashion_archive/backend/api/high_fashion_routes.py`
- Favorites API: `/Users/bhavyajain/Code/fashion_archive/backend/api/favorites_routes.py`
- Auth API: `/Users/bhavyajain/Code/fashion_archive/backend/api/auth_routes.py`

**Frontend:**
- Main app: `/Users/bhavyajain/Code/fashion_archive/web_ui/src/App.js`
- API service: `/Users/bhavyajain/Code/fashion_archive/web_ui/src/services/api.js`
- My Brands (OLD): `/Users/bhavyajain/Code/fashion_archive/web_ui/src/components/MyBrandsPanel.js`

**Launcher:**
- `/Users/bhavyajain/Code/fashion_archive/run_modern_ui.sh`

**Legacy (deprecated):**
- `/Users/bhavyajain/Code/fashion_archive/clean_api.py` - No longer used

---

## Success! 🎉

The unified backend is complete, tested, and ready for production use. All high-fashion, favorites, and authentication functionality works exactly as before, plus you now have 22 new premium scraper endpoints for brand and product management.

**Ready for:** Frontend rebuild of My Brands page using the new unified APIs.
