"""Recuperação de senha — esqueci a senha + reset via token."""
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, timedelta
from uuid import uuid4
import secrets
import logging

from app.config import settings
from app.infrastructure.database import get_db
from app.infrastructure.database.models import UserModel, PasswordResetModel
from app.infrastructure.email import send_email, render_password_reset_email
from app.infrastructure.audit import write_audit
import bcrypt

router = APIRouter()
logger = logging.getLogger(__name__)

_TOKEN_TTL = timedelta(hours=1)


class ForgotPasswordDTO(BaseModel):
    email: EmailStr


class ResetPasswordWithTokenDTO(BaseModel):
    token: str = Field(..., min_length=20, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


async def _send_reset_email_bg(user_email: str, user_name: str, reset_link: str):
    html, text = render_password_reset_email(user_name=user_name, reset_link=reset_link)
    await send_email(to=user_email, subject="Recuperação de senha · Financ-BI", html=html, text=text)


@router.post("/forgot-password", status_code=200)
async def forgot_password(
    body: ForgotPasswordDTO,
    req: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Inicia o processo de recuperação de senha.
    NOTA: Resposta SEMPRE 200 para não revelar se o email existe (boa prática).
    """
    r = await db.execute(select(UserModel).where(UserModel.email == body.email))
    user = r.scalar_one_or_none()

    if user and user.is_active:
        # Invalidar tokens anteriores não usados
        r_old = await db.execute(select(PasswordResetModel).where(and_(
            PasswordResetModel.user_id == user.id,
            PasswordResetModel.used_at == None,
        )))
        for t in r_old.scalars().all():
            t.used_at = datetime.utcnow()

        # Gerar novo token
        token = secrets.token_urlsafe(32)
        pr = PasswordResetModel(
            id=uuid4(),
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + _TOKEN_TTL,
            ip_address=req.client.host if req.client else None,
        )
        db.add(pr)
        await db.commit()

        # Enviar email em background (não bloquear resposta)
        reset_link = f"{settings.app_base_url}/reset-password?token={token}"
        background.add_task(_send_reset_email_bg, user.email, user.full_name, reset_link)

        logger.info(f"Password reset solicitado para {user.email}")
    else:
        # Não revelar se o email existe
        logger.info(f"Password reset solicitado para email inexistente/inactivo: {body.email}")

    return {"message": "Se o email existir na nossa base de dados, receberá um link de recuperação dentro de minutos."}


@router.get("/verify-reset-token/{token}")
async def verify_reset_token(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Verifica se o token é válido (sem usar). Para o frontend mostrar formulário ou erro."""
    r = await db.execute(select(PasswordResetModel, UserModel).join(
        UserModel, PasswordResetModel.user_id == UserModel.id
    ).where(PasswordResetModel.token == token))
    row = r.first()
    if not row:
        raise HTTPException(404, "Link inválido ou expirado")
    pr, user = row
    if pr.used_at is not None:
        raise HTTPException(410, "Este link já foi utilizado")
    if pr.expires_at < datetime.utcnow():
        raise HTTPException(410, "Este link expirou. Solicite um novo.")
    if not user.is_active:
        raise HTTPException(403, "Conta desactivada")
    return {"valid": True, "email": user.email, "full_name": user.full_name}


@router.post("/reset-password", status_code=200)
async def reset_password(
    body: ResetPasswordWithTokenDTO,
    req: Request,
    db: AsyncSession = Depends(get_db),
):
    """Conclui o reset com a nova senha."""
    r = await db.execute(select(PasswordResetModel, UserModel).join(
        UserModel, PasswordResetModel.user_id == UserModel.id
    ).where(PasswordResetModel.token == body.token))
    row = r.first()
    if not row:
        raise HTTPException(404, "Link inválido")
    pr, user = row
    if pr.used_at is not None:
        raise HTTPException(410, "Este link já foi utilizado")
    if pr.expires_at < datetime.utcnow():
        raise HTTPException(410, "Este link expirou. Solicite um novo.")
    if not user.is_active:
        raise HTTPException(403, "Conta desactivada")

    # Actualizar senha
    pwd_bytes = body.new_password.encode("utf-8")[:72]
    user.hashed_password = bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")
    user.updated_at = datetime.utcnow()
    pr.used_at = datetime.utcnow()

    await write_audit(
        db, user.id, user.company_id,
        "password_reset", "user", user.id,
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    logger.info(f"Password resetada com sucesso para {user.email}")
    return {"message": "Senha redefinida com sucesso. Pode fazer login.", "email": user.email}


__all__ = ["router"]
