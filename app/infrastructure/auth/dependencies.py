from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional
from app.infrastructure.database import get_db
from app.infrastructure.auth import decode_token
from app.infrastructure.repositories import UserRepository
from app.domain.entities import User

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = decode_token(token)

    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    repo = UserRepository(db)
    user = await repo.get_by_id(UUID(user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilizador não encontrado")
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "SUSPENDED", "message": "Conta suspensa pelo administrador."},
        )

    # Atualizar last_activity_at (best-effort, sem bloquear o pedido)
    try:
        from sqlalchemy import text
        from datetime import datetime as _dt
        await db.execute(
            text("UPDATE users SET last_activity_at = :now WHERE id::text = :uid"),
            {"now": _dt.utcnow(), "uid": str(user.id)},
        )
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass

    return user


async def _user_has_permission(db: AsyncSession, user: User, codigo: str) -> bool:
    """Verifica se o utilizador tem uma permissão.

    Autorização 100% baseada em Grupos: o utilizador só tem uma permissão se
    o seu grupo a possuir. Sem grupo_id ⇒ sem permissões.
    """
    from sqlalchemy import text

    u_r = await db.execute(
        text("SELECT grupo_id, is_superadmin FROM users WHERE id::text = :uid"),
        {"uid": str(user.id)},
    )
    row = u_r.first()
    if not row:
        return False
    grupo_id, is_superadmin = row[0], row[1]
    if is_superadmin:
        return True
    if not grupo_id:
        return False

    r = await db.execute(
        text(
            "SELECT 1 FROM grupo_permissoes gp "
            "JOIN permissoes p ON p.id = gp.permissao_id "
            "WHERE gp.grupo_id::text = :gid AND p.codigo = :codigo LIMIT 1"
        ),
        {"gid": str(grupo_id), "codigo": codigo},
    )
    return r.scalar_one_or_none() is not None


# ────────────────────────────────────────────────────────────────────
# Dependencies de conveniência — wrappers finos sobre uma permissão sentinela.
# Mantêm os nomes legados (require_admin/financeiro/assistente) para não
# alterar os ~15 call-sites, mas hoje decidem apenas pelo grupo.
# ────────────────────────────────────────────────────────────────────

async def require_admin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    if await _user_has_permission(db, current_user, "grupos.gerir"):
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado")


async def require_financeiro(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    if await _user_has_permission(db, current_user, "movimentos.editar"):
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado")


async def require_assistente(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    if await _user_has_permission(db, current_user, "movimentos.criar"):
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado")


def require_permission(codigo: str):
    """Factory: devolve uma dependency que exige a permissão `codigo`.

    Uso:
        @router.post(..., dependencies=[Depends(require_permission("movimentos.criar"))])
        ou
        current_user: User = Depends(require_permission("movimentos.criar"))
    """
    async def _checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if await _user_has_permission(db, current_user, codigo):
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sem permissão: requer '{codigo}'",
        )
    return _checker


__all__ = [
    "get_current_user",
    "require_admin", "require_financeiro", "require_assistente",
    "require_permission",
]
