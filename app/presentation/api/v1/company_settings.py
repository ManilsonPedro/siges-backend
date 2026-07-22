from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.application.dtos import CompanySettingsResponseDTO, CompanySettingsUpdateDTO
from app.config import settings
from app.infrastructure.database import get_db
from app.infrastructure.database.models import CompanySettingsModel
from app.infrastructure.auth.dependencies import get_current_user, require_admin
from app.domain.entities import User

router = APIRouter()

_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/svg+xml"}
_MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB


async def _get_or_create(db: AsyncSession, company_id) -> CompanySettingsModel:
    result = await db.execute(select(CompanySettingsModel).where(CompanySettingsModel.company_id == company_id))
    row = result.scalar_one_or_none()
    if row is None:
        row = CompanySettingsModel(company_id=company_id, nome="")
        db.add(row)
        await db.flush()
    return row


def _to_dto(row: CompanySettingsModel, request: Request) -> CompanySettingsResponseDTO:
    logo_url = None
    if row.logo_path:
        base = str(request.base_url).rstrip("/")
        logo_url = f"{base}/uploads/{row.logo_path}"
    return CompanySettingsResponseDTO(
        company_id=row.company_id,
        nome=row.nome or "",
        nif=row.nif,
        morada=row.morada,
        telefone=row.telefone,
        email=row.email,
        iban_bcs=row.iban_bcs,
        iban_bfa=row.iban_bfa,
        logo_path=row.logo_path,
        logo_url=logo_url,
        updated_at=row.updated_at,
    )


@router.get("", response_model=CompanySettingsResponseDTO)
async def obter_configuracoes(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _get_or_create(db, current_user.company_id)
    await db.commit()
    return _to_dto(row, request)


@router.put("", response_model=CompanySettingsResponseDTO)
async def atualizar_configuracoes(
    body: CompanySettingsUpdateDTO,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    row = await _get_or_create(db, current_user.company_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    row.updated_by = current_user.id
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return _to_dto(row, request)


@router.post("/logo", response_model=CompanySettingsResponseDTO)
async def upload_logo(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, detail=f"Formato não suportado. Use PNG, JPG, WEBP ou SVG.")

    content = await file.read()
    if len(content) > _MAX_LOGO_SIZE:
        raise HTTPException(400, detail="Logo demasiado grande (máx 2 MB).")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "png"
    ext = ext if ext in {"png", "jpg", "jpeg", "webp", "svg"} else "png"
    fname = f"logo_{current_user.company_id}_{uuid4().hex[:8]}.{ext}"

    storage_dir = Path(settings.storage_path) / "logos"
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / fname).write_bytes(content)

    row = await _get_or_create(db, current_user.company_id)
    if row.logo_path:
        old = Path(settings.storage_path) / row.logo_path
        try:
            old.unlink(missing_ok=True)
        except Exception:
            pass
    row.logo_path = f"logos/{fname}"
    row.updated_by = current_user.id
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return _to_dto(row, request)


@router.delete("/logo", response_model=CompanySettingsResponseDTO)
async def remover_logo(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    row = await _get_or_create(db, current_user.company_id)
    if row.logo_path:
        old = Path(settings.storage_path) / row.logo_path
        try:
            old.unlink(missing_ok=True)
        except Exception:
            pass
        row.logo_path = None
        row.updated_by = current_user.id
        row.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(row)
    return _to_dto(row, request)


__all__ = ["router"]
