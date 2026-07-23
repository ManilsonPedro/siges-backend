from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "SIGES BI JENNOS"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"
    log_level: str = "INFO"

    db_url: str = "sqlite+aiosqlite:///./financeiro.db"
    db_echo: bool = False
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl: int = 3600

    # JWT
    jwt_secret_key: str = "dev-secret-key-financeiro-2024"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 120
    jwt_refresh_token_expire_days: int = 7

    # CORS — separar múltiplas origens por vírgula no env var CORS_ORIGINS
    cors_origins: str = "http://localhost:3000,http://localhost:8000,http://localhost"

    # Storage: "local" guarda em disco; "b2" usa Backblaze B2
    storage_type: str = "local"
    storage_path: str = "./uploads"

    # SMTP / Email (Outlook 365)
    smtp_host: str = "smtp-mail.outlook.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "SIGES BI JENNOS"
    app_base_url: str = "http://localhost:3000"

    # Celery (não utilizado actualmente)
    celery_broker_url: str = "amqp://guest:guest@localhost//"
    celery_result_backend: str = "redis://localhost:6379/1"

    # MinIO (legado — substituído por B2)
    minio_url: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin123"
    minio_bucket: str = "financeiro"

    # Backblaze B2 (S3-compatible)
    b2_key_id: str = ""
    b2_app_key: str = ""
    b2_bucket: str = "financ-bi-jennos-aquasan"
    b2_endpoint: str = "https://s3.us-east-005.backblazeb2.com"
    b2_region: str = "us-east-005"

    @field_validator("db_url", mode="before")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        # Neon/Render fornecem postgres:// ou postgresql:// (psycopg2 dialect)
        # psycopg3 async precisa de postgresql+psycopg://
        if isinstance(v, str):
            if v.startswith("postgres://"):
                v = v.replace("postgres://", "postgresql+psycopg://", 1)
            elif v.startswith("postgresql://"):
                v = v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    @property
    def allowed_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def database(self):
        return _DatabaseProxy(self)

    @property
    def redis(self):
        return _RedisProxy(self)

    @property
    def jwt(self):
        return _JWTProxy(self)


class _DatabaseProxy:
    def __init__(self, s: Settings):
        self.url = s.db_url
        self.echo = s.db_echo
        self.pool_size = s.db_pool_size
        self.max_overflow = s.db_max_overflow
        self.pool_pre_ping = s.db_pool_pre_ping


class _RedisProxy:
    def __init__(self, s: Settings):
        self.url = s.redis_url
        self.ttl = s.redis_ttl


class _JWTProxy:
    def __init__(self, s: Settings):
        self.secret_key = s.jwt_secret_key
        self.algorithm = s.jwt_algorithm
        self.access_token_expire_minutes = s.jwt_access_token_expire_minutes
        self.refresh_token_expire_days = s.jwt_refresh_token_expire_days


import os as _os
_env_file = ".env.dev" if _os.path.exists(".env.dev") else ".env" if _os.path.exists(".env") else None
settings = Settings(_env_file=_env_file)
