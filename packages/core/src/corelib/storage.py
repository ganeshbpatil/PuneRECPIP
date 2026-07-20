"""Object storage for large crawl artifacts (raw HTML, clean HTML, markdown,
screenshots) — see docs/architecture/01-architecture.md §5: these never belong
in Postgres, only their storage keys do (`corelib.models.CrawlSnapshot`).

Two implementations behind one Protocol, per Module 1 §8's recommendation:
`LocalFilesystemObjectStorage` for dev/tests (zero external services),
`S3ObjectStorage` for anything S3-API-compatible (AWS S3 in prod, MinIO
self-hosted) — swapping one for the other is a config change, not a rewrite.
"""

import asyncio
from pathlib import Path
from typing import Protocol

import boto3
from botocore.exceptions import ClientError


class ObjectNotFoundError(Exception):
    def __init__(self, key: str):
        self.key = key
        super().__init__(f"object not found: {key}")


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...


class LocalFilesystemObjectStorage:
    """Stores objects as plain files under `base_dir/<key>`. Dev/test backend —
    no bucket, no credentials, nothing to run."""

    def __init__(self, base_dir: Path | str):
        self._base_dir = Path(base_dir)

    def _path_for(self, key: str) -> Path:
        base = self._base_dir.resolve()
        path = (self._base_dir / key).resolve()
        if base != path and base not in path.parents:
            raise ValueError(f"key {key!r} escapes the storage base directory")
        return path

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get(self, key: str) -> bytes:
        try:
            return self._path_for(key).read_bytes()
        except FileNotFoundError:
            raise ObjectNotFoundError(key) from None

    async def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()


class S3ObjectStorage:
    """S3-API-compatible backend (AWS S3, MinIO, ...). Uses boto3 (no official
    async S3 client is as mature/stable as boto3 itself) via `asyncio.to_thread`
    rather than a third-party async wrapper, so the actual AWS SDK behavior —
    retries, credential resolution, error types — is exactly what's documented."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        access_key: str | None = None,
        secret_key: str | None = None,
    ):
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise ObjectNotFoundError(key) from exc
            raise
        return await asyncio.to_thread(response["Body"].read)

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise
        return True
