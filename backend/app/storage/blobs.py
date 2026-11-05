"""Firmware artifact storage. Blobs are content-addressed by SHA-256, so object
keys never derive from user-supplied names (path-traversal resistant)."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Protocol

from ..validation import SHA256_HEX


class BlobStore(Protocol):
    def put(self, data: bytes) -> str: ...
    def local_path(self, key: str) -> Path: ...
    def exists(self, key: str) -> bool: ...


class LocalBlobStore:
    """Filesystem store used for local development and tests (verified)."""

    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not SHA256_HEX.match(key):
            raise ValueError("invalid blob key")
        p = (self.root / key[:2] / key).resolve()
        if self.root not in p.parents:
            raise ValueError("blob path escapes store root")
        return p

    def put(self, data: bytes) -> str:
        key = hashlib.sha256(data).hexdigest()
        dest = self._path(key)
        if dest.exists():
            return key
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dest.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return key

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3BlobStore:
    """AWS S3 / MinIO store. NOT exercised in the build environment (boto3 and
    network were unavailable); provided for the optional cloud path."""

    def __init__(self, bucket: str, cache_dir: str, endpoint_url: str | None = None):
        import boto3  # noqa: PLC0415 - optional dependency

        self.bucket = bucket
        self.s3 = boto3.client("s3", endpoint_url=endpoint_url)
        self.cache = LocalBlobStore(cache_dir)

    def put(self, data: bytes) -> str:
        key = self.cache.put(data)
        self.s3.put_object(Bucket=self.bucket, Key=f"firmware/{key}", Body=data,
                           ServerSideEncryption="AES256", ChecksumAlgorithm="SHA256")
        return key

    def local_path(self, key: str) -> Path:
        p = self.cache.local_path(key)
        if not p.exists():
            obj = self.s3.get_object(Bucket=self.bucket, Key=f"firmware/{key}")
            data = obj["Body"].read()
            if hashlib.sha256(data).hexdigest() != key:
                raise ValueError("S3 object digest mismatch")
            self.cache.put(data)
        return p

    def exists(self, key: str) -> bool:
        return self.cache.exists(key)
