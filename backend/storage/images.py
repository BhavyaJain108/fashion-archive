"""Where downloaded images live.

Two implementations behind one interface:

- `R2ImageStore` puts objects in Cloudflare R2 and returns their public CDN URL.
  This is what production uses, because the Render service has no persistent
  disk — anything written to the container's filesystem disappears on the next
  deploy.
- `LocalImageStore` writes to a directory and returns an API URL that serves the
  file back. This keeps local development working with no cloud credentials.

Both return a URL, never a filesystem path. That is the substantive change: the
old code returned absolute paths like
`/Users/.../backend/high_fashion/cache/images/Balenciaga/look1.jpg`, which the
frontend then handed back to `/api/image?path=` for the server to read off disk.
Those paths were meaningless on any other machine, and the endpoint that read
them would happily accept any path the client sent.

R2 is chosen when it is configured; otherwise local. Nothing above this module
knows which one is in use.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import quote


class ImageStore(Protocol):
    def save(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        """Store bytes under `key`, returning a URL that serves them."""

    def url_for(self, key: str) -> str:
        """The URL `key` would be served from, without storing anything."""

    def exists(self, key: str) -> bool:
        """Whether the object is already stored, so a caller can skip the work."""


# The image types this archive actually stores, pinned rather than looked up.
#
# `mimetypes.guess_type` reads the host's mime database, so its answer depends
# on the machine: Linux ships /etc/mime.types, which maps .ico to
# image/vnd.microsoft.icon, while macOS has no such file and Python's built-in
# table gives image/x-icon. Since R2 serves an object with whatever type it was
# uploaded with, that difference is durable — the same picture ends up stored
# with a different content type depending on where the upload ran.
_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".avif": "image/avif",
    # image/x-icon rather than the registered image/vnd.microsoft.icon: it is
    # what browsers have always accepted, and what the rest of the app expects.
    ".ico": "image/x-icon",
}


def guess_content_type(key: str) -> str:
    """Content type from the file extension.

    Worth getting right: R2 serves objects with whatever type they were uploaded
    with, so a wrong one makes the browser download the file instead of
    displaying it.

    Known image extensions resolve from the table above so the answer is the
    same on every machine; anything else still falls back to the platform's
    mime database.
    """
    suffix = PurePosixPath(key).suffix.lower()
    if suffix in _CONTENT_TYPES:
        return _CONTENT_TYPES[suffix]

    guessed, _ = mimetypes.guess_type(key)
    return guessed or "application/octet-stream"


class R2ImageStore:
    """Cloudflare R2 via its S3-compatible API.

    Objects are public and served straight from the bucket's custom domain, so
    image loads never touch the API server. That is the point of R2 here: it
    charges nothing for outbound traffic, and an image archive is almost
    entirely outbound.
    """

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_base: str,
        client=None,
    ):
        self._bucket = bucket
        self._public_base = public_base.rstrip("/")

        if client is not None:
            self._client = client
        else:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name="auto",
            )

    def save(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type or guess_content_type(key),
        )
        return self.url_for(key)

    def url_for(self, key: str) -> str:
        # quote the path segments but keep the separators, so a filename with a
        # space or an accent survives the round trip.
        return f"{self._public_base}/{quote(key, safe='/')}"

    def exists(self, key: str) -> bool:
        """Whether the object is already stored. Lets a re-scrape skip work."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False


class LocalImageStore:
    """Development fallback: a directory plus an API URL.

    `root` is absolute. The old code used paths relative to the working
    directory, so starting the server from elsewhere wrote images somewhere
    unexpected and then failed to find them.
    """

    def __init__(self, *, root: Path | str, api_base: str):
        self._root = Path(root).resolve()
        self._api_base = api_base.rstrip("/")
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes, *, content_type: str | None = None) -> str:
        path = self._safe_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.url_for(key)

    def url_for(self, key: str) -> str:
        return f"{self._api_base}/api/images/{quote(key, safe='/')}"

    def read(self, key: str) -> bytes | None:
        path = self._safe_path(key)
        return path.read_bytes() if path.is_file() else None

    def exists(self, key: str) -> bool:
        return self._safe_path(key).is_file()

    def _safe_path(self, key: str) -> Path:
        """Resolve a key inside the root, refusing anything that escapes it.

        Keys reach this from scraped filenames and from request paths, so
        `../../etc/passwd` is a real input, not a hypothetical one.
        """
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"image key escapes the store root: {key!r}")
        return candidate


# --------------------------------------------------------------------------
# Key naming
# --------------------------------------------------------------------------
# Keys are the object's identity in the bucket and its public URL, so they are
# built in one place rather than assembled at each call site.


def _slug(value: str) -> str:
    """A filesystem- and URL-safe fragment."""
    cleaned = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in value.strip())
    return cleaned.strip("._") or "unknown"


def runway_key(designer: str, filename: str) -> str:
    return f"runway/{_slug(designer)}/{_slug(filename)}"


def product_image_key(domain: str, content_hash: str, extension: str) -> str:
    """Where one archived product photograph lives.

    Content-addressed: the key is the sha256 of the bytes, so the same photograph
    reached through two product pages is stored once, and re-running the archiver
    over a brand rewrites the same objects rather than accumulating copies. The
    two-character shard keeps any one prefix from holding tens of thousands of
    objects, which is only a listing convenience — R2 does not care, but anyone
    looking through the bucket does.
    """
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"archive/{_slug(domain)}/{content_hash[:2]}/{content_hash}{ext}"


def favicon_key(brand_id: str, extension: str) -> str:
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"favicons/{_slug(brand_id)}{ext}"


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

_store: ImageStore | None = None


def configure(config) -> ImageStore:
    """Pick a store from configuration. R2 when set up, otherwise local disk."""
    global _store

    if config.R2_ACCOUNT_ID and config.R2_ACCESS_KEY_ID and config.R2_BUCKET:
        _store = R2ImageStore(
            account_id=config.R2_ACCOUNT_ID,
            access_key_id=config.R2_ACCESS_KEY_ID,
            secret_access_key=config.R2_SECRET_ACCESS_KEY,
            bucket=config.R2_BUCKET,
            public_base=config.R2_PUBLIC_BASE,
        )
    else:
        _store = LocalImageStore(root=config.IMAGE_CACHE_DIR, api_base=config.API_BASE_URL)

    return _store


def get_store() -> ImageStore:
    if _store is None:
        raise RuntimeError("image store not configured; call configure() at startup")
    return _store


def set_store(store: ImageStore) -> None:
    """Used by tests to inject a stub."""
    global _store
    _store = store
