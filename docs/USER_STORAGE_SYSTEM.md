# User Storage System

**Date:** 2025-11-16
**Status:** ✅ Implemented and Tested

## Overview

The Fashion Archive now implements a complete user-specific storage system. All user data is isolated per user, while central brand/product data remains shared.

---

## Architecture

### Central vs User-Specific Data

**Central Data (Shared):**
```
data/brands/          # All brand and product data (shared across users)
├── {brand_id}/
│   ├── info.json
│   ├── products/
│   └── images/
```

**User-Specific Data (Isolated):**
```
data/user_data/
├── users.db          # User accounts and sessions
└── {user_folder}/    # Individual user data
    ├── favourites/   # User's favorite fashion looks
    │   ├── favourites.db
    │   └── images/
    ├── brand_collections/  # User's brand following
    │   └── following.db
    └── downloads/    # User's downloaded content
```

---

## User Data Structure

### User Folder Layout

Each user gets a unique folder (`user_001`, `user_002`, etc.):

```
data/user_data/user_001/
├── favourites/
│   ├── favourites.db        # Favourite looks database
│   └── images/              # Cached favourite images
├── brand_collections/
│   └── following.db         # Brands user is following
└── downloads/               # User downloads
```

### Favourites System

**Location:** `data/user_data/{user_folder}/favourites/`

**Database Schema:**
```sql
CREATE TABLE favourites (
    id INTEGER PRIMARY KEY,
    -- Season metadata
    season_name TEXT,
    season_url TEXT,
    -- Collection metadata
    collection_designer TEXT,
    collection_url TEXT,
    -- Look metadata
    look_number INTEGER,
    image_path TEXT,
    -- User metadata
    date_added TIMESTAMP,
    notes TEXT
)
```

**Features:**
- ✅ User-specific favourites (isolated per user)
- ✅ Automatic image copying to user's favourites directory
- ✅ Complete metadata tracking
- ✅ Orphaned image cleanup

### Brand Following System

**Location:** `data/user_data/{user_folder}/brand_collections/`

**Database Schema:**
```sql
CREATE TABLE following (
    id INTEGER PRIMARY KEY,
    brand_id TEXT UNIQUE,
    brand_name TEXT,
    date_followed TIMESTAMP,
    notes TEXT,
    -- Notification preferences
    notify_new_products BOOLEAN,
    notify_price_changes BOOLEAN
)
```

**Features:**
- ✅ Track which brands user follows
- ✅ Notification preferences per brand
- ✅ Custom notes for each brand
- ✅ Isolated per user

---

## API Endpoints

### Favourites API (6 endpoints, all require auth)

All favourites endpoints are **user-specific** and require authentication:

```bash
# Get user's favourites
GET /api/favourites
Headers: Authorization: Bearer {session_token}

# Add to favourites
POST /api/favourites
Headers: Authorization: Bearer {session_token}
Body: {
  "season": {"name": "...", "url": "..."},
  "collection": {"designer": "...", "url": "..."},
  "look": {"lookNumber": 1, "total": 50},
  "image_path": "...",
  "notes": "Optional notes"
}

# Remove from favourites
DELETE /api/favourites
Headers: Authorization: Bearer {session_token}
Body: {
  "season_url": "...",
  "collection_url": "...",
  "look_number": 1
}

# Check if favourited
POST /api/favourites/check
Headers: Authorization: Bearer {session_token}
Body: {
  "season_url": "...",
  "collection_url": "...",
  "look_number": 1
}

# Get favourites stats
GET /api/favourites/stats
Headers: Authorization: Bearer {session_token}

# Cleanup orphaned images
POST /api/favourites/cleanup
Headers: Authorization: Bearer {session_token}
```

### Brand Following API (6 endpoints, all require auth)

All brand following endpoints are **user-specific** and require authentication:

```bash
# Follow a brand
POST /api/brands/follow
Headers: Authorization: Bearer {session_token}
Body: {
  "brand_id": "brand_123",
  "brand_name": "Gucci",
  "notes": "Optional notes"
}

# Unfollow a brand
POST /api/brands/unfollow
Headers: Authorization: Bearer {session_token}
Body: {
  "brand_id": "brand_123"
}

# Check if following
POST /api/brands/check-following
Headers: Authorization: Bearer {session_token}
Body: {
  "brand_id": "brand_123"
}

# Get all followed brands
GET /api/brands/following
Headers: Authorization: Bearer {session_token}

# Update notification preferences
POST /api/brands/notifications
Headers: Authorization: Bearer {session_token}
Body: {
  "brand_id": "brand_123",
  "notify_new_products": true,
  "notify_price_changes": false
}

# Update brand notes
POST /api/brands/notes
Headers: Authorization: Bearer {session_token}
Body: {
  "brand_id": "brand_123",
  "notes": "My notes about this brand"
}
```

---

## Authentication Flow

### How User Context Works

1. **User logs in** → receives `session_token`
2. **Frontend stores** session token (localStorage/cookie)
3. **Every request** includes token in Authorization header
4. **Backend middleware** (`@require_auth`) validates token
5. **`get_current_user()`** returns current user object
6. **User-specific data** loaded based on `user.user_folder`

### Example Usage in Code

```python
from backend.auth.user_system.middleware import get_current_user
from backend.high_fashion.favourites_db import FavouritesDB

def add_favourite():
    # Get current user from session
    user = get_current_user()

    # Get user-specific favourites database
    user_favourites_dir = user.get_data_path("favourites")
    favourites_db = FavouritesDB(user_favourites_dir)

    # Now working with THIS user's favourites only
    favourites_db.add_favourite(...)
```

---

## Updated File Paths

### Backend Auth System

All paths updated to use `data/user_data`:

**`backend/auth/user_system/models.py`:**
```python
# User data paths
def get_data_path(self, subfolder: str = "") -> str:
    base_path = f"data/user_data/{self.user_folder}"
    return f"{base_path}/{subfolder}" if subfolder else base_path

# User database
def __init__(self, db_path: str = "data/user_data/users.db"):
    self.db_path = db_path

# Create user directories
user_path = Path(f"data/user_data/{user_folder}")
user_path.mkdir(parents=True, exist_ok=True)
(user_path / "favourites").mkdir(exist_ok=True)
(user_path / "brand_collections").mkdir(exist_ok=True)
(user_path / "downloads").mkdir(exist_ok=True)
```

### Favourites Database

**`backend/high_fashion/favourites_db.py`:**
```python
# Changed from "favourites" to user-specific path
# (Now instantiated per-user in API routes)
def __init__(self, favourites_base_dir="data/favourites"):
    self.favourites_base_dir = Path(favourites_base_dir)
```

---

## Data Isolation

### What's User-Specific?

✅ **Favourites** - Each user has their own favourite looks
✅ **Brand Following** - Each user follows different brands
✅ **Downloads** - User-specific downloaded content
✅ **Preferences** - Notification settings per user

### What's Shared?

✅ **Brand Data** - `data/brands/` contains all products (shared)
✅ **High Fashion Cache** - nowfashion.com images (shared)
✅ **Scraper Results** - All scraped data (shared)

---

## Benefits

### Security
- ✅ Users can only access their own favourites
- ✅ Authentication required for all user-specific endpoints
- ✅ Session-based authorization

### Scalability
- ✅ Easy to add new users
- ✅ No data conflicts between users
- ✅ Clean separation of concerns

### Organization
- ✅ Clear directory structure
- ✅ All user data in one place
- ✅ Easy backup per user

---

## Testing

### Create Test User

```bash
# Register/login
curl -X POST http://localhost:8081/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "test123", "action": "register"}'

# Response includes session_token
{
  "success": true,
  "session_token": "abc123...",
  "user": {
    "id": 1,
    "username": "testuser",
    "user_folder": "user_001"
  }
}
```

### Test Favourites

```bash
# Add favourite (with session token)
curl -X POST http://localhost:8081/api/favourites \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer abc123..." \
  -d '{
    "season": {"name": "Spring 2024", "url": "..."},
    "collection": {"designer": "Gucci", "url": "..."},
    "look": {"lookNumber": 1, "total": 50},
    "image_path": "path/to/image.jpg"
  }'

# Get favourites (user-specific)
curl http://localhost:8081/api/favourites \
  -H "Authorization: Bearer abc123..."
```

### Test Brand Following

```bash
# Follow a brand
curl -X POST http://localhost:8081/api/brands/follow \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer abc123..." \
  -d '{"brand_id": "gucci", "brand_name": "Gucci"}'

# Get followed brands
curl http://localhost:8081/api/brands/following \
  -H "Authorization: Bearer abc123..."
```

---

## Migration Notes

### Changed Files

1. **`backend/auth/user_system/models.py`**
   - Updated all paths from `user_data/` to `data/user_data/`
   - Added `parents=True` to mkdir calls

2. **`backend/api/favorites_routes.py`**
   - Added `get_current_user()` to all endpoints
   - Create user-specific `FavouritesDB` instance per request
   - Applied `@require_auth` middleware to all endpoints

3. **`backend/high_fashion/favourites_db.py`**
   - Updated default path from `favourites` to `data/favourites`

4. **`backend/api/brand_following_routes.py`** (NEW)
   - Complete brand following API

5. **`backend/auth/user_system/brand_following.py`** (NEW)
   - Brand following database manager

6. **`backend/app.py`**
   - Registered brand following routes
   - Updated endpoint count to 45

---

## Summary

✅ **All user data is now isolated per user**
✅ **Favourites are user-specific**
✅ **Brand following is user-specific**
✅ **Central brand data remains shared**
✅ **All user endpoints require authentication**
✅ **Clean data directory structure**
✅ **45 total API endpoints (6 new for brand following)**

The system is production-ready with complete user data isolation! 🎉
