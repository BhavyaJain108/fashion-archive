"""Shared pytest config.

Two roots on the path. The repo root serves the absolute imports the archive and
the API use (`from backend.archive...`); `backend/` serves the flat ones the auth,
userdata and storage tests use (`from auth.tokens import ...`), which mirror how
`backend/app.py` is run. The old scraper's flat imports were a third reason for
this and are gone, but the first two remain.
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
