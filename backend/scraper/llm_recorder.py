"""LLM fixture recorder.

Opt-in recording of Claude calls (input + output + metadata) so we can replay
them offline against cheaper providers during evaluation.

Activation (opt-in; pipeline is untouched when disabled):
    LLM_RECORD=1                   # master switch
    LLM_RECORD_DIR=tests/fixtures/llm   # default
    LLM_RECORD_BRAND=khaite.com    # pipeline sets this per scrape

On success, writes:
    {dir}/{stage}/{operation}/{brand}_{hash8}.json   # fixture
    {dir}/{stage}/{operation}/{brand}_{hash8}.png    # vision image (if any)
    {dir}/index.jsonl                                # append-only manifest

Design notes:
- fixture_id = sha256(prompt + image_hash)[:12]. Idempotent — re-running the
  same input overwrites the same file, so fixtures don't multiply.
- Only successful calls are recorded. Failures are transient (429s, validation
  retries) and not useful as ground truth.
- Recording errors never break the pipeline: all file I/O is wrapped.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def is_recording_enabled() -> bool:
    """True when LLM_RECORD=1 (or any truthy value)."""
    return os.getenv("LLM_RECORD", "").strip().lower() in ("1", "true", "yes", "on")


def _default_record_dir() -> Path:
    """Resolve the fixture directory from env, with a repo-relative default."""
    env_dir = os.getenv("LLM_RECORD_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    # Default: tests/fixtures/llm relative to repo root.
    # llm_recorder.py lives at backend/scraper/llm_recorder.py → go up 3 levels.
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "tests" / "fixtures" / "llm"


def _slug(value: str) -> str:
    """Filesystem-safe slug: lowercase, non-alphanum → underscores."""
    if not value:
        return "unknown"
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unknown"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_fixture_id(prompt: str, image_b64: str | None = None) -> str:
    """Deterministic ID: first 12 hex chars of sha256(prompt || image_sha256).

    Stable across processes so repeat calls overwrite the same fixture.
    """
    h = hashlib.sha256()
    h.update(prompt.encode("utf-8"))
    if image_b64:
        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception:
            # Corrupt b64 — hash the string form so we still get a stable id
            image_bytes = image_b64.encode("utf-8")
        h.update(b"\x00")  # separator
        h.update(_hash_bytes(image_bytes).encode("ascii"))
    return h.hexdigest()[:12]


class FixtureRecorder:
    """Writes recorded LLM calls to disk. Thread-safe (index.jsonl appended
    under a lock)."""

    _index_lock = threading.Lock()

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else _default_record_dir()

    # ---- Public API ---------------------------------------------------------

    def record_call(
        self,
        *,
        method: str,
        prompt: str,
        output: dict[str, Any],
        operation: str,
        stage: str,
        model: str,
        max_tokens: int,
        response_model: str | None = None,
        image_b64: str | None = None,
        image_media_type: str | None = None,
        brand: str | None = None,
    ) -> Path | None:
        """Record one LLM call. Returns the fixture path, or None if skipped /
        recording failed. Never raises — failures are logged and swallowed."""
        try:
            if not output or not output.get("success"):
                return None  # Only record successful calls

            brand = brand or os.getenv("LLM_RECORD_BRAND") or "unknown"
            fixture_id = compute_fixture_id(prompt, image_b64)

            stage_slug = _slug(stage or "unknown")
            op_slug = _slug(operation or "unknown")
            brand_slug = _slug(brand)

            target_dir = self.base_dir / stage_slug / op_slug
            target_dir.mkdir(parents=True, exist_ok=True)

            fixture_path = target_dir / f"{brand_slug}_{fixture_id}.json"
            image_path: Path | None = None
            image_sha: str | None = None

            # Write image alongside the JSON, keep JSON diff-friendly
            if image_b64:
                try:
                    image_bytes = base64.b64decode(image_b64)
                    image_sha = _hash_bytes(image_bytes)
                    image_path = target_dir / f"{brand_slug}_{fixture_id}.png"
                    image_path.write_bytes(image_bytes)
                except Exception as e:  # noqa: BLE001
                    print(f"[llm_recorder] failed to write image: {e}")
                    image_path = None

            fixture = {
                "fixture_id": fixture_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "method": method,
                "operation": operation,
                "stage": stage,
                "brand": brand,
                "model": model,
                "input": {
                    "prompt": prompt,
                    "prompt_sha256": _hash_text(prompt),
                    "max_tokens": max_tokens,
                    "response_model": response_model,
                    "image_ref": (
                        {
                            "path": image_path.name,
                            "media_type": image_media_type,
                            "sha256": image_sha,
                        }
                        if image_path and image_sha
                        else None
                    ),
                },
                "output": _sanitize_output(output),
            }

            fixture_path.write_text(
                json.dumps(fixture, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )

            self._append_index(
                {
                    "fixture_id": fixture_id,
                    "timestamp": fixture["timestamp"],
                    "stage": stage,
                    "operation": operation,
                    "brand": brand,
                    "method": method,
                    "model": model,
                    "path": str(fixture_path.relative_to(self.base_dir)),
                }
            )

            return fixture_path
        except Exception as e:  # noqa: BLE001
            # Recording must never take down the pipeline.
            print(f"[llm_recorder] WARNING: recording failed: {e}")
            return None

    # ---- Internal -----------------------------------------------------------

    def _append_index(self, entry: dict[str, Any]) -> None:
        index_path = self.base_dir / "index.jsonl"
        try:
            with self._index_lock:
                self.base_dir.mkdir(parents=True, exist_ok=True)
                with index_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, sort_keys=True) + "\n")
        except Exception as e:  # noqa: BLE001
            print(f"[llm_recorder] WARNING: index append failed: {e}")


def _sanitize_output(output: dict[str, Any]) -> dict[str, Any]:
    """Copy of output with non-JSON-serializable values stringified."""
    safe: dict[str, Any] = {}
    for key, value in output.items():
        try:
            json.dumps(value)
            safe[key] = value
        except (TypeError, ValueError):
            safe[key] = repr(value)
    return safe


# ---- Module-level singleton --------------------------------------------------

_recorder_singleton: FixtureRecorder | None = None
_singleton_lock = threading.Lock()


def get_recorder() -> FixtureRecorder | None:
    """Return the module-level recorder if recording is enabled, else None."""
    if not is_recording_enabled():
        return None
    global _recorder_singleton
    if _recorder_singleton is None:
        with _singleton_lock:
            if _recorder_singleton is None:
                _recorder_singleton = FixtureRecorder()
    return _recorder_singleton
