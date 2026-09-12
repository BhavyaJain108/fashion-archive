"""Where the archive keeps its objects.

Two implementations behind one protocol: a directory during development and in the
tests, R2 in production. Both support conditional writes, because that is what lets
parallel workers claim a brand with no database behind them — and a test that mocked
it would be testing nothing. The live bucket was probed before this was written: R2
refuses a stale If-Match with PreconditionFailed, which is the behaviour relied on.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol

# What the bucket answers when an object is not there, and when a condition fails.
_ABSENT = ("NoSuchKey", "404", "NoSuchBucket")
_REFUSED = ("PreconditionFailed", "412")


class Conflict(RuntimeError):
    """A conditional write was refused: someone else got there first."""


class ObjectStore(Protocol):
    def get(self, key: str) -> tuple[bytes, str] | None:
        """The object's body and etag, or None when it is not there."""

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        """Write, returning the new etag. Raises Conflict if a condition fails."""

    def list(self, prefix: str) -> list[str]:
        """Keys under this prefix, sorted."""

    def delete(self, key: str) -> None:
        """Remove the object. Absent is not an error."""


def _etag(body: bytes) -> str:
    # md5 to match what S3 returns for a single-part upload, so the directory store
    # and R2 hand out etags of the same shape. Not used for anything security-bearing.
    return hashlib.md5(body, usedforsecurity=False).hexdigest()


class DirectoryObjectStore:
    """A directory, with the same conditional-write semantics as the bucket.

    Writes land through a temporary file and a rename, so a reader never sees half an
    object — the same guarantee R2 gives, and the reason a killed run leaves the last
    flushed state rather than a truncated one.
    """

    def __init__(self, root: Path):
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"object key escapes the store root: {key!r}")
        return candidate

    def get(self, key: str) -> tuple[bytes, str] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        body = path.read_bytes()
        return body, _etag(body)

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        path = self._path(key)
        current = self.get(key)
        if if_none_match and current is not None:
            raise Conflict(f"{key} already exists")
        if if_match is not None and (current is None or current[1] != if_match):
            raise Conflict(f"{key} changed under us")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        return _etag(body)

    def list(self, prefix: str) -> list[str]:
        keys = []
        for path in self._root.rglob("*"):
            if not path.is_file() or path.name.endswith(".tmp"):
                continue
            key = str(path.relative_to(self._root))
            if key.startswith(prefix):
                keys.append(key)
        return sorted(keys)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def _r2_client():
    import boto3

    from config.config import config

    return boto3.client(
        "s3",
        endpoint_url=f"https://{config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=config.R2_ACCESS_KEY_ID,
        aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


class R2ObjectStore:
    """Cloudflare R2 over its S3 API — the same bucket the photographs are in.

    The prefix keeps the two apart: the store writes under `archive-store/` and the
    images under `archive/`, so listing one never walks the other. Callers pass keys
    without it, because which bucket layout is in use is this module's business.
    """

    def __init__(self, bucket: str, client: Any = None, prefix: str = ""):
        self._bucket = bucket
        self._prefix = prefix
        self._client = client if client is not None else _r2_client()

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> tuple[bytes, str] | None:
        from botocore.exceptions import ClientError

        try:
            response = self._client.get_object(Bucket=self._bucket, Key=self._key(key))
        except ClientError as error:
            if error.response["Error"]["Code"] in _ABSENT:
                return None
            raise
        return response["Body"].read(), response["ETag"].strip('"')

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        from botocore.exceptions import ClientError

        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": self._key(key),
            "Body": body,
            "ContentType": "application/json",
        }
        if if_none_match:
            kwargs["IfNoneMatch"] = "*"
        if if_match is not None:
            kwargs["IfMatch"] = if_match
        try:
            response = self._client.put_object(**kwargs)
        except ClientError as error:
            if error.response["Error"]["Code"] in _REFUSED:
                raise Conflict(f"{key} changed under us") from error
            raise
        return response["ETag"].strip('"')

    def list(self, prefix: str) -> list[str]:
        keys = []
        pages = self._client.get_paginator("list_objects_v2")
        for page in pages.paginate(Bucket=self._bucket, Prefix=self._key(prefix)):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"][len(self._prefix) :])
        return sorted(keys)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._key(key))


def object_store(local_root: Path | None = None) -> ObjectStore:
    """R2 when it is configured, a directory when it is not.

    One answer to "where does the archive keep things", decided in one place — the
    same shape backend/storage/images.py uses for the photographs.
    """
    from config.config import config

    if config.R2_ACCOUNT_ID and config.R2_ACCESS_KEY_ID and config.R2_BUCKET:
        return R2ObjectStore(config.R2_BUCKET, prefix="archive-store/")
    return DirectoryObjectStore(local_root or Path("backend/archive/data/objects"))


def dumps(value: Any) -> bytes:
    """One JSON encoding for every object.

    Sorted keys and no incidental whitespace, so writing the same content twice yields
    the same etag — which is what makes a compare-and-swap mean "did this change"
    rather than "was this rewritten".
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def loads(body: bytes) -> Any:
    return json.loads(body)
