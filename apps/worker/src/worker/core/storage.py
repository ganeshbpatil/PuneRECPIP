from corelib.storage import LocalFilesystemObjectStorage, ObjectStorage, S3ObjectStorage

from worker.core.config import Settings, get_settings


def get_object_storage(settings: Settings | None = None) -> ObjectStorage:
    settings = settings or get_settings()
    if settings.object_storage_backend == "local":
        return LocalFilesystemObjectStorage(settings.object_storage_local_dir)
    if settings.object_storage_backend == "s3":
        return S3ObjectStorage(
            settings.object_storage_bucket,
            endpoint_url=settings.object_storage_endpoint_url,
            region_name=settings.object_storage_region,
            access_key=settings.object_storage_access_key,
            secret_key=settings.object_storage_secret_key,
        )
    raise ValueError(f"unknown object_storage_backend: {settings.object_storage_backend!r}")
