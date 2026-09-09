"""Image archiver: the files, not just the URLs — CDNs forget, archives don't (spec §4.4)."""

import hashlib
from pathlib import Path

from backend.archive.store.catalog import Catalog
from backend.archive.transport import Transport

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


class ImageStore:
    def __init__(self, root: Path, width: int | None = None):
        self.root = root
        self.width = width  # Shopify CDN resizes on the fly; None = original resolution

    def _fetch_url(self, url: str) -> str:
        if self.width and "cdn.shopify.com" in url:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}width={self.width}"
        return url

    def archive(
        self, transport: Transport, catalog: Catalog, product_id: int, domain: str, urls: list[str]
    ) -> int:
        known = catalog.known_image_urls(product_id)
        saved = 0
        for url in urls:
            if url in known:
                continue
            try:
                resp = transport.get(self._fetch_url(url))
            except Exception:
                continue  # a missing image never fails a run
            ctype = resp.headers.get("content-type", "").split(";")[0].strip()
            if resp.status_code != 200 or not ctype.startswith("image/"):
                continue
            sha = hashlib.sha256(resp.content).hexdigest()
            path = self.root / domain / sha[:2] / f"{sha}{_EXT.get(ctype, '.bin')}"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(resp.content)
            catalog.record_image(product_id, url, str(path), sha)
            saved += 1
        return saved
