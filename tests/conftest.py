"""Shared pytest config.

The backend uses flat top-level imports (`from stages.storage import ...`)
and runs with `backend/` as the working dir. We mirror that here so tests
can `from stages.urls import dedupe_urls_by_path`. We also expose the repo
root for any future test that needs to reach web_ui/ or config/.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"

for path in (BACKEND_ROOT, REPO_ROOT):
    p = str(path)
    if p not in sys.path:
        sys.path.insert(0, p)
