import boto3
import pytest
from corelib.storage import LocalFilesystemObjectStorage, ObjectNotFoundError, S3ObjectStorage
from moto import mock_aws

pytestmark = pytest.mark.asyncio


async def test_local_put_get_roundtrip(tmp_path):
    storage = LocalFilesystemObjectStorage(tmp_path)
    await storage.put("crawls/co1/home.html", b"<html>hi</html>", content_type="text/html")

    assert await storage.exists("crawls/co1/home.html") is True
    assert await storage.get("crawls/co1/home.html") == b"<html>hi</html>"


async def test_local_get_missing_raises_not_found(tmp_path):
    storage = LocalFilesystemObjectStorage(tmp_path)
    assert await storage.exists("nope") is False
    with pytest.raises(ObjectNotFoundError):
        await storage.get("nope")


async def test_local_rejects_path_escape(tmp_path):
    storage = LocalFilesystemObjectStorage(tmp_path)
    with pytest.raises(ValueError):
        await storage.put("../escape.txt", b"data", content_type="text/plain")


async def test_s3_put_get_roundtrip():
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-artifacts")
        storage = S3ObjectStorage("test-artifacts", region_name="us-east-1")

        await storage.put("crawls/co1/home.html", b"<html>hi</html>", content_type="text/html")

        assert await storage.exists("crawls/co1/home.html") is True
        assert await storage.get("crawls/co1/home.html") == b"<html>hi</html>"


async def test_s3_get_missing_raises_not_found():
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-artifacts")
        storage = S3ObjectStorage("test-artifacts", region_name="us-east-1")

        assert await storage.exists("nope") is False
        with pytest.raises(ObjectNotFoundError):
            await storage.get("nope")
