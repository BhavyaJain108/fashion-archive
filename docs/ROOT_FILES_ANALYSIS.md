# Root Directory Files Analysis

**Date:** 2025-11-16

## File Classification

### 🟢 KEEP - Currently Used

| File | Purpose | Used By | Action |
|------|---------|---------|--------|
| `config.py` | Centralized configuration (PORT, HOST, API keys) | `backend/app.py`, all API modules | **KEEP** - Essential |
| `run_modern_ui.sh` | Launch script for backend + frontend | User | **KEEP** - Main entry point |
| `.env` | Environment variables (API keys, config) | `config.py` | **KEEP** - Essential |
| `.env.example` | Example environment file | Documentation | **KEEP** - For setup |
| `requirements.txt` | Python dependencies | pip install | **KEEP** - Essential |
| `requirements-deploy.txt` | Deployment-specific requirements | Deployment | **KEEP** |
| `README.md` | Project documentation | Users/developers | **KEEP** |
| `LICENSE` | MIT License | Legal | **KEEP** |
| `.gitignore` | Git ignore rules | Git | **KEEP** |

### 🟡 ORGANIZE - Utility Scripts (Move to `tools/`)

These are standalone CLI utilities that aren't part of the core backend/frontend:

| File | Purpose | Status | Recommendation |
|------|---------|--------|----------------|
| `collection_organizer.py` | Organizes downloaded image folders by collection | Standalone CLI | **Move to `tools/`** |
| `image_downloader.py` | Generic image scraper/downloader | Standalone CLI | **Move to `tools/`** |
| `google_video_search.py` | Google video search for fashion shows | Standalone CLI | **Move to `tools/`** |
| `claude_video_verifier.py` | AI-powered video verification | Standalone CLI | **Move to `tools/`** |
| `youtube_downloader.py` | YouTube video downloader | Standalone CLI | **Move to `tools/`** |
| `video_player_widget.py` | Video player UI widget | Standalone CLI | **Move to `tools/`** or **DELETE** if unused |
| `debug_pagination_logic.py` | Debug script for pagination | Debug/dev | **Move to `tools/debug/`** or **DELETE** |

### 🟡 ORGANIZE - High Fashion Related (Move to `backend/high_fashion/`)

| File | Purpose | Current Location | Recommendation |
|------|---------|------------------|----------------|
| `llm_interface.py` | LLM API client wrapper | Root | **Move to `backend/high_fashion/llm_interface.py`** |

**Why:** It's used by `google_video_search.py` which is a high-fashion tool.

### 🔴 DELETE/ARCHIVE - Legacy Files

| File | Purpose | Status | Recommendation |
|------|---------|--------|----------------|
| `legacy_clean_api.py` | Old monolithic backend (900 lines) | Replaced by `backend/app.py` | **ARCHIVE** - Already renamed, can delete after verification |
| `deploy_config.py` | Old deployment config | Unknown if used | **CHECK** then delete or move to `tools/` |
| `config_example.json` | Old JSON config example | Replaced by `.env.example` | **DELETE** |

### 📄 DOCUMENTATION FILES

| File | Purpose | Status | Recommendation |
|------|---------|--------|----------------|
| `BACKEND_REORGANIZATION.md` | Backend reorganization docs | Current | **Move to `docs/`** |
| `PREMIUM_SCRAPER_API.md` | Premium scraper API docs | Current | **Move to `docs/`** |
| `PROJECT_STRUCTURE.md` | Project structure overview | Current | **Move to `docs/`** |
| `STUFF.md` | Miscellaneous notes | Unknown | **Review** then delete or move to `docs/notes/` |

---

## Recommended Directory Structure

```
fashion_archive/
├── backend/                        # Backend code
│   ├── app.py
│   ├── api/
│   ├── high_fashion/
│   ├── storage/
│   ├── services/
│   └── scraper/
├── web_ui/                         # Frontend code
│   └── src/
├── tools/                          # 🆕 Utility scripts
│   ├── collection_organizer.py
│   ├── image_downloader.py
│   ├── google_video_search.py
│   ├── claude_video_verifier.py
│   ├── youtube_downloader.py
│   ├── video_player_widget.py
│   └── debug/
│       └── debug_pagination_logic.py
├── docs/                           # 🆕 Documentation
│   ├── BACKEND_REORGANIZATION.md
│   ├── PREMIUM_SCRAPER_API.md
│   ├── PROJECT_STRUCTURE.md
│   └── notes/
│       └── STUFF.md
├── data/                           # Data storage
│   └── brands/
├── logs/                           # Log files
├── tests/                          # Test files
├── config.py                       # ✅ KEEP
├── .env                            # ✅ KEEP
├── .env.example                    # ✅ KEEP
├── requirements.txt                # ✅ KEEP
├── requirements-deploy.txt         # ✅ KEEP
├── run_modern_ui.sh                # ✅ KEEP
├── README.md                       # ✅ KEEP
├── LICENSE                         # ✅ KEEP
└── .gitignore                      # ✅ KEEP
```

---

## Detailed File Analysis

### Utility Scripts Analysis

**1. collection_organizer.py (27KB)**
- **Purpose:** Analyzes folders of downloaded images, identifies main collection, removes non-matching images
- **Dependencies:** None (standalone)
- **Used by:** Manual CLI use
- **Recommendation:** Move to `tools/` - it's a utility for organizing downloaded content

**2. image_downloader.py (14KB)**
- **Purpose:** Generic configurable image scraper/downloader
- **Dependencies:** requests, BeautifulSoup
- **Used by:** Manual CLI use
- **Recommendation:** Move to `tools/` - standalone scraping utility

**3. google_video_search.py (39KB)**
- **Purpose:** Uses Google search to find fashion runway show videos
- **Dependencies:** `llm_interface.py` (for AI verification)
- **Used by:** Manual CLI use
- **Recommendation:** Move to `tools/` along with `llm_interface.py`

**4. claude_video_verifier.py (25KB)**
- **Purpose:** AI-powered video verification using Claude to validate fashion show videos
- **Dependencies:** anthropic, llm libraries
- **Used by:** `google_video_search.py`
- **Recommendation:** Move to `tools/` - pairs with google_video_search

**5. youtube_downloader.py (10KB)**
- **Purpose:** Downloads videos from YouTube
- **Dependencies:** yt-dlp
- **Used by:** Manual CLI use, possibly `google_video_search.py`
- **Recommendation:** Move to `tools/`

**6. video_player_widget.py (11KB)**
- **Purpose:** Tkinter video player widget
- **Dependencies:** tkinter, opencv
- **Used by:** Unknown - may be legacy
- **Recommendation:** Check if used, otherwise DELETE

**7. debug_pagination_logic.py (2.3KB)**
- **Purpose:** Debug script for testing pagination
- **Dependencies:** None
- **Used by:** Development only
- **Recommendation:** Move to `tools/debug/` or DELETE if no longer needed

**8. llm_interface.py (5.9KB)**
- **Purpose:** Wrapper for LLM API clients (OpenAI, Anthropic)
- **Dependencies:** openai, anthropic
- **Used by:** `google_video_search.py`, `claude_video_verifier.py`
- **Recommendation:** Move to `backend/high_fashion/` since it's high-fashion related

---

## Implementation Plan

### Phase 1: Create New Directories
```bash
mkdir -p tools/debug
mkdir -p docs/notes
```

### Phase 2: Move Utility Scripts
```bash
mv collection_organizer.py tools/
mv image_downloader.py tools/
mv google_video_search.py tools/
mv claude_video_verifier.py tools/
mv youtube_downloader.py tools/
mv video_player_widget.py tools/  # or delete
mv debug_pagination_logic.py tools/debug/
```

### Phase 3: Move LLM Interface
```bash
mv llm_interface.py backend/high_fashion/
```

Update imports in:
- `tools/google_video_search.py`
- `tools/claude_video_verifier.py`

### Phase 4: Move Documentation
```bash
mv BACKEND_REORGANIZATION.md docs/
mv PREMIUM_SCRAPER_API.md docs/
mv PROJECT_STRUCTURE.md docs/
mv STUFF.md docs/notes/  # after reviewing
```

### Phase 5: Clean Up Legacy
```bash
# After verification that backend works:
rm legacy_clean_api.py
rm config_example.json  # if not needed
```

### Phase 6: Review deploy_config.py
- Check if it's used in deployment
- If yes: Keep or move to `tools/`
- If no: Delete

---

## Why This Organization?

**Benefits:**
1. ✅ **Clean root directory** - Only essential files visible
2. ✅ **Clear separation** - Tools vs backend vs docs
3. ✅ **Better discoverability** - Utilities in `tools/`, docs in `docs/`
4. ✅ **Easier maintenance** - Related files grouped together
5. ✅ **Professional structure** - Standard project layout

**Root directory after cleanup:**
```
fashion_archive/
├── backend/
├── web_ui/
├── tools/
├── docs/
├── data/
├── logs/
├── tests/
├── config.py
├── .env
├── .env.example
├── requirements.txt
├── requirements-deploy.txt
├── run_modern_ui.sh
├── README.md
├── LICENSE
└── .gitignore
```

Much cleaner! 🎉

---

## Dependencies to Check

Before moving `llm_interface.py`, verify:
```bash
grep -r "import llm_interface\|from llm_interface" .
```

Before deleting `video_player_widget.py`, verify:
```bash
grep -r "import video_player_widget\|from video_player_widget" .
```

---

## Summary

**Current Root:** 25+ files (cluttered)
**After Cleanup:** ~14 files (clean and organized)

**Next Step:** Review and approve this plan, then execute the reorganization.
