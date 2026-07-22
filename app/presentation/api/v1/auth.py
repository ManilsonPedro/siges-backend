from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List
from app.application.dtos import (
    LoginRequestDTO,
    TokenResponseDTO,
    UserResponseDTO,
    UserCreateDTO,
    UserUpdateDTO,
    ResetPasswordDTO,
    RefreshTokenDTO,
    ChangePasswordDTO,
)
from app.infrastructure.database import get_db
from app.infrastructure.auth import create_access_token, create_refresh_token, verify_password, hash_password, decode_token
from app.infrastructure.auth.dependencies import get_current_user, _user_has_permission
from app.infrastructure.repositories import UserRepository
from app.domain.entities import User

router = APIRouter()


def _user_to_dto(u: User) -> UserResponseDTO:
    return UserResponseDTO(
        id=u.id,
        company_id=u.company_id,
        email=u.email,
        full_name=u.full_name,
        is_active=u.is_active,
        is_superadmin=getattr(u, "is_superadmin", False) or False,
        must_change_password=getattr(u, "must_change_password", False) or False,
        grupo_id=getattr(u, "grupo_id", None),
        created_at=u.created_at,
        updated_at=u.updated_at,
    )


@router.post("/login", response_model=TokenResponseDTO)
async def login(request: LoginRequestDTO, db: AsyncSession = Depends(get_db)):
    print(f">>> LOGIN endpoint chamado para email={request.email}", flush=True)
    try:
        repo = UserRepository(db)
        user = await repo.get_by_email(request.email)
        print(f">>> user encontrado: {user is not None}", flush=True)
        if not user or not verify_password(request.password, user.hashed_password):
            print(f">>> credenciais inválidas para {request.email}", flush=True)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta desativada")
        token = create_access_token(user.id, user.company_id)
        refresh = create_refresh_token(user.id, user.company_id)
        # Regista last_login_at e last_activity_at
        try:
            from sqlalchemy import text as _t
            from datetime import datetime as _dt
            now = _dt.utcnow()
            await db.execute(
                _t("UPDATE users SET last_login_at = :now, last_activity_at = :now WHERE id::text = :uid"),
                {"now": now, "uid": str(user.id)},
            )
            await db.commit()
        except Exception:
            try: await db.rollback()
            except Exception: pass
        print(f">>> login OK para {user.email}", flush=True)
        return TokenResponseDTO(access_token=token, refresh_token=refresh)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"\n{'='*60}\n!!! ERRO em /auth/login: {type(e).__name__}: {e}\n{traceback.format_exc()}{'='*60}\n", flush=True)
        raise


@router.post("/register", response_model=UserResponseDTO, status_code=status.HTTP_201_CREATED)
async def register(request: UserCreateDTO, db: AsyncSession = Depends(get_db)):
    repo = UserRepository(db)
    if await repo.get_by_email(request.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email já registado")
    user = User(
        email=request.email,
        full_name=request.full_name,
        hashed_password=hash_password(request.password),
    )
    created = await repo.create(user)
    await db.commit()
    return _user_to_dto(created)


@router.get("/me", response_model=UserResponseDTO)
async def get_me(current_user: User = Depends(get_current_user)):
    return _user_to_dto(current_user)


@router.get("/permissions")
async def get_my_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Devolve a lista de códigos de permissão do utilizador (via grupo)."""
    from sqlalchemy import text
    u_r = await db.execute(
        text("SELECT grupo_id FROM users WHERE id::text = :uid"),
        {"uid": str(current_user.id)},
    )
    grupo_id = u_r.scalar_one_or_none()
    if not grupo_id:
        return {"grupo_id": None, "permissions": []}
    r = await db.execute(
        text(
            "SELECT p.codigo FROM grupo_permissoes gp "
            "JOIN permissoes p ON p.id = gp.permissao_id "
            "WHERE gp.grupo_id::text = :gid"
        ),
        {"gid": str(grupo_id)},
    )
    codes = [row[0] for row in r.all()]
    return {"grupo_id": str(grupo_id), "permissions": codes}


@router.post("/refresh", response_model=TokenResponseDTO)
async def refresh_token(body: RefreshTokenDTO):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido")
    user_id = UUID(payload["sub"])
    company_id = UUID(payload["company_id"])
    return TokenResponseDTO(
        access_token=create_access_token(user_id, company_id),
        refresh_token=create_refresh_token(user_id, company_id),
    )


@router.post("/logout")
async def logout():
    return {"message": "Logout efectuado com sucesso"}


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password actual incorrecta")
    repo = UserRepository(db)
    user = await repo.get_by_id(current_user.id)
    user.hashed_password = hash_password(body.new_password)
    user.must_change_password = False
    await repo.update(current_user.id, user)
    await db.commit()


# ── Gestão de utilizadores ────────────────────────────────────────────────────

@router.get("/users", response_model=List[UserResponseDTO])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await _user_has_permission(db, current_user, "users.listar"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito")
    repo = UserRepository(db)
    users = await repo.get_all()
    return [_user_to_dto(u) for u in users if u.company_id == current_user.company_id]


@router.post("/users", response_model=UserResponseDTO, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: UserCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await _user_has_permission(db, current_user, "users.gerir"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito")
    repo = UserRepository(db)
    if await repo.get_by_email(request.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email já registado")
    # Senha por defeito = email; força mudança no primeiro login
    pwd_raw = request.password or request.email
    user = User(
        company_id=current_user.company_id,
        email=request.email,
        full_name=request.full_name,
        hashed_password=hash_password(pwd_raw),
        must_change_password=True,
    )
    try:
        created = await repo.create(user)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao criar utilizador: {e}")
    return _user_to_dto(created)


@router.put("/users/{id}", response_model=UserResponseDTO)
async def update_user(
    id: UUID,
    body: UserUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    can_manage = await _user_has_permission(db, current_user, "users.gerir")
    if not can_manage and current_user.id != id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão")
    repo = UserRepository(db)
    user = await repo.get_by_id(id)
    if not user or user.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilizador não encontrado")
    if body.email and body.email != user.email:
        if await repo.get_by_email(body.email):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email já em uso")
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.email is not None:
        user.email = body.email
    if body.is_active is not None and can_manage:
        user.is_active = body.is_active
    updated = await repo.update(id, user)
    # Marca/limpa suspended_at consoante is_active
    if body.is_active is not None and can_manage:
        from sqlalchemy import text as _t
        from datetime import datetime as _dt
        if body.is_active:
            await db.execute(_t("UPDATE users SET suspended_at = NULL WHERE id::text = :uid"), {"uid": str(id)})
        else:
            await db.execute(_t("UPDATE users SET suspended_at = :now WHERE id::text = :uid"), {"now": _dt.utcnow(), "uid": str(id)})
    await db.commit()
    return _user_to_dto(updated)


@router.post("/users/{id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    id: UUID,
    body: ResetPasswordDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await _user_has_permission(db, current_user, "users.gerir") and current_user.id != id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão")
    repo = UserRepository(db)
    user = await repo.get_by_id(id)
    if not user or user.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilizador não encontrado")
    user.hashed_password = hash_password(body.new_password)
    await repo.update(id, user)
    await db.commit()


@router.delete("/users/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await _user_has_permission(db, current_user, "users.gerir"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito")
    if current_user.id == id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Não pode eliminar a sua própria conta")
    repo = UserRepository(db)
    user = await repo.get_by_id(id)
    if not user or user.company_id != current_user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilizador não encontrado")
    user.is_active = False
    await repo.update(id, user)
    await db.commit()


@router.get("/users/stats")
async def users_stats(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Estatísticas de sessão dos utilizadores da empresa."""
    from sqlalchemy import text as _t
    cid = str(current_user.company_id)
    r = await db.execute(_t(
        """
        SELECT
          COUNT(*) FILTER (WHERE deleted_at IS NULL)                                                       AS total,
          COUNT(*) FILTER (WHERE deleted_at IS NULL AND is_active = TRUE)                                   AS ativos,
          COUNT(*) FILTER (WHERE deleted_at IS NULL AND is_active = FALSE)                                  AS suspensos,
          COUNT(*) FILTER (WHERE deleted_at IS NULL AND last_activity_at >= NOW() - INTERVAL '5 minutes')   AS online,
          COUNT(*) FILTER (WHERE deleted_at IS NULL AND last_login_at >= NOW() - INTERVAL '24 hours')       AS login_24h,
          COUNT(*) FILTER (WHERE deleted_at IS NULL AND last_login_at >= NOW() - INTERVAL '7 days')         AS login_7d,
          COUNT(*) FILTER (WHERE deleted_at IS NULL AND last_login_at IS NULL)                              AS nunca_logaram
        FROM users
        WHERE company_id::text = :cid
        """
    ), {"cid": cid})
    row = r.first()
    return {
        "total": row[0] or 0, "ativos": row[1] or 0, "suspensos": row[2] or 0,
        "online": row[3] or 0, "login_24h": row[4] or 0, "login_7d": row[5] or 0,
        "nunca_logaram": row[6] or 0,
    }


@router.get("/users/listagem")
async def users_listagem(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Listagem detalhada com last_login_at e last_activity_at."""
    from sqlalchemy import text as _t
    if not await _user_has_permission(db, current_user, "users.listar"):
        raise HTTPException(status_code=403, detail="Acesso restrito")
    r = await db.execute(_t(
        "SELECT id, full_name, email, is_active, grupo_id, last_login_at, last_activity_at, created_at "
        "FROM users WHERE company_id::text = :cid AND deleted_at IS NULL ORDER BY full_name"
    ), {"cid": str(current_user.company_id)})
    out = []
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.utcnow()
    for row in r.all():
        last_act = row[6]
        online = bool(last_act and (now - last_act) < _td(minutes=5))
        out.append({
            "id": str(row[0]), "full_name": row[1], "email": row[2],
            "is_active": row[3], "grupo_id": str(row[4]) if row[4] else None,
            "last_login_at": row[5].isoformat() if row[5] else None,
            "last_activity_at": last_act.isoformat() if last_act else None,
            "online": online,
            "created_at": row[7].isoformat() if row[7] else None,
        })
    return out


__all__ = ["router"]
