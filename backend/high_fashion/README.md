# High Fashion Module

This module contains all high-fashion (nowfashion.com) related functionality, including favorites management and user authentication.

## Structure

```
backend/high_fashion/
├── __init__.py                 # Module init
├── favourites_db.py            # Favorites database operations
├── user_system/                # User authentication & sessions
│   ├── __init__.py
│   ├── models.py               # User & Session models
│   ├── auth.py                 # Authentication logic
│   ├── middleware.py           # Auth middleware (@require_auth)
│   └── manager.py              # User management
├── favourites/                 # Favorites data storage
│   ├── favourites.db           # SQLite database
│   └── images/                 # Cached favorite images
└── cache/                      # High fashion cache
    ├── images/                 # Designer collection images
    └── videos/                 # Designer show videos
```

## Components

### Favorites Database (`favourites_db.py`)

Manages favorite high-fashion looks.

**Features:**
- Add/remove/check favorite looks
- SQLite database storage
- Image caching in `favourites/images/`
- Statistics and cleanup utilities

**Usage:**
```python
from backend.high_fashion.favourites_db import favourites_db

# Add a favorite
favourites_db.add_favourite(season_data, collection_data, look_data, image_path, notes)

# Check if favorited
is_fav = favourites_db.is_favourite(season_url, collection_url, look_number)

# Get all favorites
favorites = favourites_db.get_all_favourites()
```

### User System (`user_system/`)

Complete user authentication and session management.

**Components:**
- `models.py` - User and Session SQLAlchemy models
- `auth.py` - Authentication logic (login, logout, registration)
- `middleware.py` - Flask middleware for protected routes
- `manager.py` - User management utilities

**Usage:**
```python
from backend.high_fashion.user_system.auth import UserAuth
from backend.high_fashion.user_system.middleware import require_auth, get_current_user

# Initialize auth
user_auth = UserAuth()

# Login
success, user, session, message = user_auth.get_or_create_user(username, password)

# Protect route
@app.route('/api/protected')
@require_auth
def protected_route():
    user = get_current_user()
    return jsonify({'user_id': user.id})
```

### Cache Directory (`cache/`)

Temporary storage for downloaded high-fashion content.

**Subdirectories:**
- `images/` - Designer collection images by collection name
- `videos/` - Designer show videos

**Management:**
- Automatically created when downloading content
- Can be cleared via `/api/cleanup` endpoint
- Organized by designer/collection names

## API Integration

This module is used by:
- `backend/api/high_fashion_routes.py` - Seasons, collections, images, videos
- `backend/api/favorites_routes.py` - Favorites management
- `backend/api/auth_routes.py` - User authentication

## Database Files

**Favorites:**
- Location: `backend/high_fashion/favourites/favourites.db`
- Schema: SQLite with looks, seasons, collections tables

**Users:**
- Location: `users.db` (in project root)
- Schema: Users and Sessions tables

## Migration Notes

**Moved from project root:**
- `favourites_db.py` → `backend/high_fashion/favourites_db.py`
- `user_system/` → `backend/high_fashion/user_system/`
- `favourites/` → `backend/high_fashion/favourites/`
- `high_fashion_cache/` → `backend/high_fashion/cache/`

**Imports updated in:**
- `backend/api/favorites_routes.py`
- `backend/api/auth_routes.py`
- `backend/api/high_fashion_routes.py`

All functionality preserved and tested working.
