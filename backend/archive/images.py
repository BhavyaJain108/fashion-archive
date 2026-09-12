"""Image archiver: the files, not just the URLs — CDNs forget, archives don't (spec §4.4).

Where the bytes go is the sink's decision, not this module's. In development that is a
directory; in production it is the R2 bucket the site already serves images from. What
the catalogue records either way is the URL the photograph is served from, because a
path under one laptop's home directory meant nothing on any other machine — and 20 GB
of photographs was never going to live on the laptop that runs the scraper.
"""

import hashlib
from pathlib import Path

from backend.archive.store.catalog import Catalog
from backend.archive.transport import Transport
from backend.storage.images import ImageStore as Sink
from backend.storage.images import product_image_key

_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}


class ImageStore:
    def __init__(self, sink: Sink, width: int | None = None):
        self.sink = sink
        self.width = width  # Shopify CDN resizes on the fly; None = original resolution

    def _fetch_url(self, url: str) -> str:
        if self.width and "cdn.shopify.com" in url:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}width={self.width}"
        return url

    def store(self, domain: str, content: bytes, content_type: str) -> tuple[str, str]:
        """Put one image in the sink. Returns (content hash, served URL)."""
        sha = hashlib.sha256(content).hexdigest()
        key = product_image_key(domain, sha, _EXT.get(content_type, ".bin"))
        # An object already in the bucket has the same bytes — the key is their hash —
        # so re-uploading it would buy nothing but a write.
        url = self.sink.url_for(key) if self.sink.exists(key) else self.sink.save(key, content)
        return sha, url

    def archive(
        self, transport: Transport, catalog: Catalog, itemurl: str, domain: str, urls: list[str]
    ) -> int:
        known = catalog.stored_image_urls(domain, itemurl)
        stored = 0
        for url in urls:
            if url in known:
                continue  # delta economics: an unchanged image costs zero requests
            try:
                resp = transport.get(self._fetch_url(url))
            except Exception:
                continue  # a missing image never fails a run
            ctype = resp.headers.get("content-type", "").split(";")[0].strip()
            if resp.status_code != 200 or not ctype.startswith("image/"):
                continue
            sha, served = self.store(domain, resp.content, ctype)
            catalog.record_image(domain, itemurl, url, sha, stored_url=served)
            stored += 1
        return stored

    def adopt(self, catalog: Catalog, itemurl: str, domain: str, url: str, path: Path) -> bool:
        """Move an image an earlier run already fetched into the sink, off disk.

        Same bytes, so the shop is not asked for them a second time.
        """
        try:
            content = path.read_bytes()
        except OSError:
            return False
        ctype = _CONTENT_TYPE_BY_SUFFIX.get(path.suffix.lower(), "image/jpeg")
        sha, served = self.store(domain, content, ctype)
        catalog.record_image(domain, itemurl, url, sha, stored_url=served)
        return True


_CONTENT_TYPE_BY_SUFFIX = {v: k for k, v in _EXT.items()}
