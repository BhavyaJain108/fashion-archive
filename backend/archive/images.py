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


# A photograph is a few megabytes at most; a "photograph" of 40 MB is something else.
MAX_IMAGE_BYTES = 15 * 1024 * 1024

_IMAGE_MAGIC = (
    b"\xff\xd8\xff",  # JPEG
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"GIF87a",
    b"GIF89a",
    b"BM",  # BMP
)


def looks_like_image(data: bytes) -> bool:
    """Whether the bytes start the way an image file does. WebP and AVIF/HEIC carry
    their signature a few bytes in; SVG is text and is not accepted — it can script."""
    head = data[:16]
    if any(head.startswith(m) for m in _IMAGE_MAGIC):
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    return head[4:8] == b"ftyp"  # AVIF / HEIC


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
        return sum(
            self.archive_one(transport, catalog, itemurl, domain, url)
            for url in urls
            if url not in known  # delta economics: an unchanged image costs zero requests
        )

    def archive_one(
        self, transport: Transport, catalog: Catalog, itemurl: str, domain: str, url: str
    ) -> bool:
        """Fetch and keep one photograph. Safe to call from several threads at once:
        the transport is shared, the budget paces per host, and recording is locked."""
        # A gallery read from a page can be cut short mid-query as well as mid-path:
        # psylos1 stores "?x-oss-process=image/resize,w_1200/format,webp/q", and the
        # server answers "the value: q of parameter: process is invalid". The bytes are
        # there without it, at full size, so a failure is worth one retry bare.
        for candidate in self._candidates(url):
            got = self._fetch(transport, candidate)
            if got is None:
                continue
            content, ctype = got
            sha, served = self.store(domain, content, ctype)
            catalog.record_image(domain, itemurl, url, sha, stored_url=served)
            return True
        catalog.record_image_miss(domain, itemurl, url)
        return False

    def _candidates(self, url: str) -> list[str]:
        fetch = self._fetch_url(url)
        bare = url.split("?", 1)[0]
        return [fetch] if bare == url else [fetch, bare]

    @staticmethod
    def _fetch(transport: Transport, url: str):
        try:
            resp = transport.get(url)
        except Exception:
            return None  # a missing image never fails a run
        ctype = resp.headers.get("content-type", "").split(";")[0].strip()
        if resp.status_code != 200 or not ctype.startswith("image/"):
            return None
        # The header is the host's claim; the first bytes are the fact. Anything else
        # would be mirrored under our own domain with an image's name.
        if len(resp.content) > MAX_IMAGE_BYTES or not looks_like_image(resp.content):
            return None
        return resp.content, ctype

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
