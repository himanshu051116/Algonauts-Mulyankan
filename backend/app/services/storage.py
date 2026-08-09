"""Storage service for MinIO-compatible object storage.

All document access uses private object keys and signed URLs.
Blocking boto3 operations are executed in worker threads.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeAlias, TypeVar

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings


logger = logging.getLogger(__name__)

JsonObject: TypeAlias = dict[str, Any]

P = ParamSpec("P")
T = TypeVar("T")


class StorageError(RuntimeError):
    """Safe storage-layer failure."""


def _get_client_error_code(exc: ClientError) -> str:
    error_response = exc.response
    if isinstance(error_response, dict):
        error_value = error_response.get("Error")
        if isinstance(error_value, dict):
            raw_code = error_value.get("Code")
            if raw_code is not None:
                return str(raw_code)
    return "Unknown"


def _require_string(
    value: object,
    *,
    context: str,
) -> str:
    """Validate that an external library returned a non-empty string."""

    if not isinstance(value, str) or not value.strip():
        raise StorageError(
            f"{context} returned an invalid string value"
        )

    return value


def _require_mapping(
    value: object,
    *,
    context: str,
) -> JsonObject:
    """Validate and normalise an external mapping."""

    if not isinstance(value, dict):
        raise StorageError(
            f"{context} returned an invalid response"
        )

    return {
        str(key): item
        for key, item in value.items()
    }


def _get_client(
    endpoint_url: str | None = None,
) -> Any:
    """Create an S3-compatible storage client."""

    return boto3.client(
        "s3",
        endpoint_url=(
            endpoint_url
            or settings.storage_endpoint
        ),
        aws_access_key_id=settings.storage_access_key,
        aws_secret_access_key=settings.storage_secret_key,
        region_name=settings.storage_region,
        config=Config(
            signature_version="s3v4",
            # S3-compatible endpoints such as Supabase Storage expose their
            # API beneath a path. Virtual-hosted bucket names would generate
            # an invalid hostname for those endpoints.
            s3={"addressing_style": "path"},
        ),
    )


def _get_presign_client() -> Any:
    """Create the client used for browser-accessible signed URLs."""

    endpoint = (
        settings.storage_public_endpoint
        or settings.storage_endpoint
    )

    return _get_client(endpoint)


async def _to_thread(
    func: Callable[P, T],
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Execute a blocking callable in a worker thread."""

    return await asyncio.to_thread(
        func,
        *args,
        **kwargs,
    )


async def get_signed_upload_url(
    storage_path: str,
    file_size: int,
    content_type: str | None = None,
) -> str:
    """Create a signed URL for uploading one private object."""

    if not storage_path.strip():
        raise StorageError(
            "Storage path cannot be empty"
        )

    if file_size <= 0:
        raise StorageError(
            "Upload file size must be greater than zero"
        )

    client = _get_client()
    bucket = settings.storage_bucket

    await _ensure_bucket_exists(
        client,
        bucket,
    )

    presign_client = _get_presign_client()

    params: JsonObject = {
        "Bucket": bucket,
        "Key": storage_path,
        "ContentLength": file_size,
    }

    if content_type:
        params["ContentType"] = content_type

    result: object = await _to_thread(
        presign_client.generate_presigned_url,
        "put_object",
        Params=params,
        ExpiresIn=3600,
        HttpMethod="PUT",
    )

    return _require_string(
        result,
        context="Presigned upload URL generation",
    )


async def get_signed_download_url(
    storage_path: str,
    expires_in: int = 3600,
) -> str:
    """Create a signed URL for downloading one private object."""

    if not storage_path.strip():
        raise StorageError(
            "Storage path cannot be empty"
        )

    if expires_in <= 0:
        raise StorageError(
            "Signed URL expiry must be greater than zero"
        )

    client = _get_presign_client()

    result: object = await _to_thread(
        client.generate_presigned_url,
        "get_object",
        Params={
            "Bucket": settings.storage_bucket,
            "Key": storage_path,
        },
        ExpiresIn=expires_in,
        HttpMethod="GET",
    )

    return _require_string(
        result,
        context="Presigned download URL generation",
    )


async def head_object(
    storage_path: str,
) -> JsonObject:
    """Retrieve metadata for a stored object."""

    if not storage_path.strip():
        raise StorageError(
            "Storage path cannot be empty"
        )

    client = _get_client()

    try:
        result: object = await _to_thread(
            client.head_object,
            Bucket=settings.storage_bucket,
            Key=storage_path,
        )
    except ClientError as exc:
        error_code = _get_client_error_code(exc)
        if error_code in ("404", "NoSuchKey", "NotFound"):
            logger.info("storage.object_not_found", extra={"key": storage_path})
            raise StorageError("Object not found") from exc
        if error_code in ("403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
            logger.warning("storage.auth_failure", extra={"key": storage_path, "code": error_code})
            raise StorageError("Storage authentication failed") from exc
        logger.warning(
            "storage.head_object_failed",
            extra={"key": storage_path, "code": error_code},
        )
        raise StorageError("Storage service is unavailable") from exc

    return _require_mapping(
        result,
        context="Storage head-object operation",
    )


async def delete_object(
    storage_path: str,
) -> None:
    """Delete an object from private storage."""

    if not storage_path.strip():
        raise StorageError(
            "Storage path cannot be empty"
        )

    client = _get_client()

    try:
        await _to_thread(
            client.delete_object,
            Bucket=settings.storage_bucket,
            Key=storage_path,
        )
    except ClientError as exc:
        logger.warning(
            "storage.delete_object_failed",
            extra={"key": storage_path},
        )

        raise StorageError(
            "Object could not be deleted"
        ) from exc


async def download_object_to_file(
    storage_path: str,
    target_path: Path,
    maximum_size: int,
) -> int:
    """Download an object while enforcing a maximum size."""

    if not storage_path.strip():
        raise StorageError(
            "Storage path cannot be empty"
        )

    if maximum_size <= 0:
        raise StorageError(
            "Maximum download size must be greater than zero"
        )

    client = _get_client()

    def download() -> int:
        try:
            raw_response: object = client.get_object(
                Bucket=settings.storage_bucket,
                Key=storage_path,
            )
        except ClientError as exc:
            logger.warning(
                "storage.download_failed",
                extra={"key": storage_path},
            )

            raise StorageError(
                "Object could not be downloaded"
            ) from exc

        response = _require_mapping(
            raw_response,
            context="Storage get-object operation",
        )

        body = response.get("Body")

        if body is None or not hasattr(body, "read"):
            raise StorageError(
                "Storage response did not contain a readable body"
            )

        target_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        total_size = 0

        try:
            with target_path.open("wb") as output_file:
                while True:
                    chunk = body.read(1024 * 1024)

                    if not chunk:
                        break

                    if not isinstance(
                        chunk,
                        bytes | bytearray,
                    ):
                        raise StorageError(
                            "Storage returned an invalid data chunk"
                        )

                    total_size += len(chunk)

                    if total_size > maximum_size:
                        raise StorageError(
                            "Object exceeds maximum permitted size"
                        )

                    output_file.write(chunk)
        finally:
            close_method = getattr(
                body,
                "close",
                None,
            )

            if callable(close_method):
                close_method()

        return total_size

    try:
        return await asyncio.to_thread(download)
    except StorageError:
        target_path.unlink(
            missing_ok=True,
        )
        raise


async def _ensure_bucket_exists(
    client: Any,
    bucket: str,
) -> None:
    """Ensure that the configured storage bucket exists."""

    if not bucket.strip():
        raise StorageError(
            "Storage bucket is not configured"
        )

    try:
        await _to_thread(
            client.head_bucket,
            Bucket=bucket,
        )
        return
    except ClientError as exc:
        error_response: object = exc.response

        error_code: str | None = None

        if isinstance(error_response, dict):
            error_value = error_response.get("Error")

            if isinstance(error_value, dict):
                raw_code = error_value.get("Code")

                if raw_code is not None:
                    error_code = str(raw_code)

        missing_bucket_codes = {
            "404",
            "NoSuchBucket",
            "NotFound",
        }

        if error_code not in missing_bucket_codes:
            logger.exception(
                "storage.bucket_head_failed",
                extra={"bucket": bucket},
            )

            raise StorageError(
                "Storage bucket is unavailable"
            ) from exc

    logger.info(
        "storage.bucket_missing_create",
        extra={"bucket": bucket},
    )

    try:
        await _to_thread(
            client.create_bucket,
            Bucket=bucket,
        )
    except ClientError as create_exc:
        create_error_response: object = create_exc.response
        create_error_code: str | None = None

        if isinstance(create_error_response, dict):
            create_error_value = create_error_response.get(
                "Error"
            )

            if isinstance(create_error_value, dict):
                raw_create_code = create_error_value.get(
                    "Code"
                )

                if raw_create_code is not None:
                    create_error_code = str(
                        raw_create_code
                    )

        already_exists_codes = {
            "BucketAlreadyExists",
            "BucketAlreadyOwnedByYou",
        }

        if create_error_code in already_exists_codes:
            return

        logger.exception(
            "storage.bucket_create_failed",
            extra={"bucket": bucket},
        )

        raise StorageError(
            "Storage bucket could not be created"
        ) from create_exc


async def check_storage_ready() -> bool:
    """Check that the configured private bucket is reachable without mutating it."""
    if not settings.storage_bucket.strip():
        return False
    client = _get_client()
    try:
        await _to_thread(client.head_bucket, Bucket=settings.storage_bucket)
    except Exception:
        return False
    return True
