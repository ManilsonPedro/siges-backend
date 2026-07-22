import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
from app.config import settings


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: UUID, company_id: UUID, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt.access_token_expire_minutes)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt.secret_key, algorithm=settings.jwt.algorithm)


def create_refresh_token(user_id: UUID, company_id: UUID) -> str:
    expires_delta = timedelta(days=settings.jwt.refresh_token_expire_days)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt.secret_key, algorithm=settings.jwt.algorithm)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt.secret_key, algorithms=[settings.jwt.algorithm])
    except jwt.PyJWTError:
        return None


# ─── Tokens do Portal do Cliente (FrontOffice) ──────────────────────
# Usam "type" distinto ("cliente_access"/"cliente_refresh") para que
# nunca sejam aceites pelas dependencies de colaborador/RBAC interno
# (get_current_user só aceita type == "access"/"refresh").


def create_cliente_access_token(conta_id: UUID, company_id: UUID, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt.access_token_expire_minutes)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(conta_id),
        "company_id": str(company_id),
        "exp": expire,
        "type": "cliente_access",
    }
    return jwt.encode(payload, settings.jwt.secret_key, algorithm=settings.jwt.algorithm)


def create_cliente_refresh_token(conta_id: UUID, company_id: UUID) -> str:
    expires_delta = timedelta(days=settings.jwt.refresh_token_expire_days)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(conta_id),
        "company_id": str(company_id),
        "exp": expire,
        "type": "cliente_refresh",
    }
    return jwt.encode(payload, settings.jwt.secret_key, algorithm=settings.jwt.algorithm)


__all__ = [
    "hash_password", "verify_password",
    "create_access_token", "create_refresh_token", "decode_token",
    "create_cliente_access_token", "create_cliente_refresh_token",
]
