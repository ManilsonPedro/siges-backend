from typing import Optional, BinaryIO
import os


class LocalStorageProvider:
    """Guarda ficheiros em disco local (dev / fallback)."""

    def __init__(self, base_path: str = "./uploads"):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)

    async def upload(self, file_path: str, file_content: BinaryIO,
                     content_type: str = "application/octet-stream") -> str:
        full_path = os.path.join(self.base_path, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(file_content.read())
        return file_path

    async def download(self, file_path: str) -> Optional[bytes]:
        full_path = os.path.join(self.base_path, file_path)
        if not os.path.exists(full_path):
            return None
        with open(full_path, "rb") as f:
            return f.read()

    async def delete(self, file_path: str) -> bool:
        full_path = os.path.join(self.base_path, file_path)
        if not os.path.exists(full_path):
            return False
        os.remove(full_path)
        return True

    def public_url(self, file_path: str) -> str:
        return f"/uploads/{file_path}"


class B2StorageProvider:
    """Backblaze B2 via API S3-compatible (boto3)."""

    def __init__(self, key_id: str, app_key: str, bucket: str,
                 endpoint: str, region: str):
        import boto3
        from botocore.config import Config
        self.bucket = bucket
        self.endpoint = endpoint.rstrip("/")
        self._s3 = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=key_id,
            aws_secret_access_key=app_key,
            region_name=region,
            config=Config(signature_version="s3v4"),
        )

    async def upload(self, file_path: str, file_content: BinaryIO,
                     content_type: str = "application/octet-stream") -> str:
        data = file_content.read() if hasattr(file_content, "read") else file_content
        self._s3.put_object(
            Bucket=self.bucket,
            Key=file_path,
            Body=data,
            ContentType=content_type,
        )
        return file_path

    async def download(self, file_path: str) -> Optional[bytes]:
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=file_path)
            return resp["Body"].read()
        except Exception:
            return None

    async def delete(self, file_path: str) -> bool:
        try:
            self._s3.delete_object(Bucket=self.bucket, Key=file_path)
            return True
        except Exception:
            return False

    def public_url(self, file_path: str) -> str:
        return f"{self.endpoint}/{self.bucket}/{file_path}"

    def presigned_url(self, file_path: str, expires: int = 3600) -> str:
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": file_path},
            ExpiresIn=expires,
        )


def get_storage_provider():
    """Devolve o provider configurado em settings."""
    from app.config import settings
    if settings.storage_type == "b2" and settings.b2_key_id and settings.b2_app_key:
        return B2StorageProvider(
            key_id=settings.b2_key_id,
            app_key=settings.b2_app_key,
            bucket=settings.b2_bucket,
            endpoint=settings.b2_endpoint,
            region=settings.b2_region,
        )
    return LocalStorageProvider(base_path=settings.storage_path)


__all__ = ["LocalStorageProvider", "B2StorageProvider", "get_storage_provider"]
