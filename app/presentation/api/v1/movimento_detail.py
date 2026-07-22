"""Detalhes ricos de um movimento — para o modal UX v2.
Endpoints:
  GET    /movimentos-detail/{id}/full      → tudo num só payload
  GET    /movimentos-detail/{id}/comentarios
  POST   /movimentos-detail/{id}/comentarios
  PUT    /movimentos-detail/{id}/comentarios/{cid}
  DELETE /movimentos-detail/{id}/comentarios/{cid}
  GET    /movimentos-detail/{id}/anexos
  POST   /movimentos-detail/{id}/anexos
  DELETE /movimentos-detail/{id}/anexos/{aid}
  POST   /movimentos-detail/{id}/mudar-estado
"""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Optional, Literal
from pathlib import Path

from app.config import settings
from app.infrastructure.storage import get_storage_provider
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    MovimentoFinanceiroModel, FornecedorModel, ConceptoModel, UserModel,
    MovimentoComentarioModel, MovimentoAnexoModel, MovimentoHistoricoModel,
    MovimentoPagamentoModel,
)
from app.infrastructure.auth.dependencies import get_current_user, require_financeiro, require_assistente, _user_has_permission
from app.infrastructure.audit import write_audit
from app.presentation.api.v1.periodos import is_periodo_fechado
from app.domain.entities import User

router = APIRouter()

_ALLOWED_MIME = {
    "application/pdf",
    "image/png", "image/jpeg", "image/jpg", "image/webp",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_COMMENT_EDIT_WINDOW = timedelta(minutes=15)


async def _get_movimento(db: AsyncSession, mov_id, company_id) -> MovimentoFinanceiroModel:
    r = await db.execute(select(MovimentoFinanceiroModel).where(
        MovimentoFinanceiroModel.id == mov_id,
    ))
    m = r.scalar_one_or_none()
    if not m or m.company_id != company_id:
        raise HTTPException(404, "Movimento não encontrado")
    return m


def _format_intervalo(start: datetime, end: Optional[datetime]) -> Optional[str]:
    if not start or not end: return None
    delta = end - start
    dias = delta.days
    horas = delta.seconds // 3600
    minutos = (delta.seconds % 3600) // 60
    parts = []
    if dias: parts.append(f"{dias}d")
    if horas: parts.append(f"{horas}h")
    if minutos or not parts: parts.append(f"{minutos}m")
    return " ".join(parts)


# ────────────────────────────────────────────────────────────────────
# GET /full — payload completo
# ────────────────────────────────────────────────────────────────────

@router.get("/{id}/full")
async def detalhe_completo(
    id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = await _get_movimento(db, id, current_user.company_id)

    # Fornecedor (opcional — só faz sentido para saídas)
    f = None
    if m.fornecedor_id:
        rf = await db.execute(select(FornecedorModel).where(FornecedorModel.id == m.fornecedor_id))
        f = rf.scalar_one_or_none()
    # Cliente (opcional — só faz sentido para entradas)
    from app.infrastructure.database.models import ClienteModel
    cli = None
    if getattr(m, "cliente_id", None):
        rcli = await db.execute(select(ClienteModel).where(ClienteModel.id == m.cliente_id))
        cli = rcli.scalar_one_or_none()
    # Conceito
    rc = await db.execute(select(ConceptoModel).where(ConceptoModel.id == m.conceito_id))
    c = rc.scalar_one_or_none()
    # Criador
    ru = await db.execute(select(UserModel).where(UserModel.id == m.created_by))
    creator = ru.scalar_one_or_none()
    # Fechador (se aplicável)
    closer = None
    if m.closed_by:
        rcl = await db.execute(select(UserModel).where(UserModel.id == m.closed_by))
        closer = rcl.scalar_one_or_none()

    # Comentários
    rcom = await db.execute(
        select(MovimentoComentarioModel, UserModel.full_name)
        .join(UserModel, MovimentoComentarioModel.user_id == UserModel.id)
        .where(and_(
            MovimentoComentarioModel.movimento_id == id,
            MovimentoComentarioModel.deleted_at == None,
        ))
        .order_by(MovimentoComentarioModel.created_at.desc())
    )
    comentarios = [{
        "id": str(co.id),
        "texto": co.texto,
        "user_id": str(co.user_id),
        "user_name": un,
        "is_owner": co.user_id == current_user.id,
        "is_editable": co.user_id == current_user.id and co.created_at and (datetime.utcnow() - co.created_at) < _COMMENT_EDIT_WINDOW,
        "edited_at": co.edited_at.isoformat() if co.edited_at else None,
        "created_at": co.created_at.isoformat() if co.created_at else None,
    } for co, un in rcom.all()]

    # Anexos (inclui eliminados para o histórico — o frontend filtra para a listagem)
    base_url = str(request.base_url).rstrip("/")
    storage = get_storage_provider()
    from sqlalchemy.orm import aliased
    UploadUser = aliased(UserModel)
    DeleteUser = aliased(UserModel)
    ran = await db.execute(
        select(MovimentoAnexoModel, UploadUser.full_name, DeleteUser.full_name)
        .outerjoin(UploadUser, MovimentoAnexoModel.uploaded_by == UploadUser.id)
        .outerjoin(DeleteUser, MovimentoAnexoModel.deleted_by == DeleteUser.id)
        .where(MovimentoAnexoModel.movimento_id == id)
        .order_by(MovimentoAnexoModel.uploaded_at.desc())
    )
    def _file_url(file_path: str) -> str:
        if hasattr(storage, "presigned_url"):
            return storage.presigned_url(file_path)
        return f"{base_url}/uploads/{file_path}"
    anexos = [{
        "id": str(a.id),
        "file_name": a.file_name,
        "file_url": _file_url(a.file_path),
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "uploaded_by_name": uname,
        "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None,
        "deleted_at": a.deleted_at.isoformat() if a.deleted_at else None,
        "deleted_by_name": dname,
        "delete_reason": a.delete_reason,
        "tipo_fatura": a.tipo_fatura,
    } for a, uname, dname in ran.all()]

    # Inclui também o `comprovativo_pagamento` legado como anexo virtual
    if m.comprovativo_pagamento:
        anexos.append({
            "id": "legacy-comprovativo",
            "file_name": Path(m.comprovativo_pagamento).name,
            "file_url": _file_url(m.comprovativo_pagamento),
            "mime_type": None,
            "size_bytes": None,
            "uploaded_by_name": creator.full_name if creator else None,
            "uploaded_at": m.created_at.isoformat() if m.created_at else None,
            "_legacy": True,
        })

    # Histórico de alterações
    rh = await db.execute(
        select(MovimentoHistoricoModel, UserModel.full_name)
        .outerjoin(UserModel, MovimentoHistoricoModel.user_id == UserModel.id)
        .where(MovimentoHistoricoModel.movimento_id == id)
        .order_by(MovimentoHistoricoModel.created_at.desc())
    )
    historico = [{
        "id": str(h.id),
        "campo": h.campo,
        "valor_anterior": h.valor_anterior,
        "valor_novo": h.valor_novo,
        "observacao": h.observacao,
        "user_name": un,
        "created_at": h.created_at.isoformat() if h.created_at else None,
        "tipo": "alteracao",
    } for h, un in rh.all()]

    # Pagamentos parciais (também entram na timeline)
    rp = await db.execute(
        select(MovimentoPagamentoModel, UserModel.full_name)
        .outerjoin(UserModel, MovimentoPagamentoModel.created_by == UserModel.id)
        .where(and_(
            MovimentoPagamentoModel.movimento_id == id,
            MovimentoPagamentoModel.deleted_at == None,
        ))
        .order_by(MovimentoPagamentoModel.created_at.desc())
    )
    pagamentos = [{
        "id": str(p.id),
        "valor": float(p.valor),
        "fundo_tipo": p.fundo_tipo,
        "data": p.data.isoformat() if p.data else None,
        "observacao": p.observacao,
        "user_name": un,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "tipo": "pagamento",
    } for p, un in rp.all()]

    return {
        "id": str(m.id),
        "codigo": m.codigo,
        "data": m.data.isoformat() if m.data else None,
        "valor": float(m.valor),
        "tipo_movimento": m.tipo_movimento,
        "fundo_tipo": m.fundo_tipo,
        "estado_pagamento": m.estado_pagamento,
        "estado_movimento": m.estado_movimento,
        "fatura_proforma": m.fatura_proforma,
        "fatura_recibo": m.fatura_recibo,
        "observacoes": m.observacoes,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "closed_at": m.closed_at.isoformat() if m.closed_at else None,
        "tempo_tratamento": _format_intervalo(m.created_at, m.closed_at) if m.closed_at else None,
        "created_by": {
            "id": str(creator.id), "nome": creator.full_name, "email": creator.email,
        } if creator else None,
        "closed_by": {
            "id": str(closer.id), "nome": closer.full_name, "email": closer.email,
        } if closer else None,
        "fornecedor": {
            "id": str(f.id), "nome": f.nome, "nif": f.nif, "telefone": f.telefone,
            "email": f.email, "endereco": f.endereco, "estado": f.estado,
        } if f else None,
        "cliente": {
            "id": str(cli.id), "nome": cli.nome, "nif": cli.nif, "telefone": cli.telefone,
            "email": cli.email, "endereco": cli.endereco, "estado": cli.estado,
        } if cli else None,
        "conceito": {
            "id": str(c.id), "nome": c.nome, "descricao": c.descricao, "estado": c.estado,
        } if c else None,
        "comentarios": comentarios,
        "anexos": anexos,
        "historico": historico,
        "pagamentos": pagamentos,
    }


# ────────────────────────────────────────────────────────────────────
# Comentários
# ────────────────────────────────────────────────────────────────────

class ComentarioCreateDTO(BaseModel):
    texto: str = Field(..., min_length=1, max_length=2000)


@router.post("/{id}/comentarios", status_code=201)
async def criar_comentario(
    id: UUID,
    body: ComentarioCreateDTO,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_movimento(db, id, current_user.company_id)
    c = MovimentoComentarioModel(
        movimento_id=id,
        company_id=current_user.company_id,
        user_id=current_user.id,
        texto=body.texto.strip(),
    )
    db.add(c)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "comentario_criado", "movimento", id,
        dados_novos={"texto": body.texto[:200]},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    await db.refresh(c)
    return {
        "id": str(c.id), "texto": c.texto,
        "user_name": current_user.full_name,
        "created_at": c.created_at.isoformat(),
        "is_owner": True, "is_editable": True,
    }


@router.put("/{id}/comentarios/{cid}")
async def editar_comentario(
    id: UUID, cid: UUID,
    body: ComentarioCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(MovimentoComentarioModel).where(MovimentoComentarioModel.id == cid))
    c = r.scalar_one_or_none()
    if not c or c.movimento_id != id or c.user_id != current_user.id:
        raise HTTPException(404, "Comentário não encontrado")
    if c.deleted_at:
        raise HTTPException(400, "Comentário eliminado")
    if (datetime.utcnow() - c.created_at) >= _COMMENT_EDIT_WINDOW:
        raise HTTPException(403, "Janela de edição expirada (15 min)")
    c.texto = body.texto.strip()
    c.edited_at = datetime.utcnow()
    await db.commit()
    return {"id": str(c.id), "texto": c.texto, "edited_at": c.edited_at.isoformat()}


@router.delete("/{id}/comentarios/{cid}", status_code=204)
async def eliminar_comentario(
    id: UUID, cid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(select(MovimentoComentarioModel).where(MovimentoComentarioModel.id == cid))
    c = r.scalar_one_or_none()
    if not c or c.movimento_id != id:
        raise HTTPException(404, "Comentário não encontrado")
    # Admins podem eliminar qualquer; outros só os seus dentro da janela
    is_admin = await _user_has_permission(db, current_user, "grupos.gerir")
    is_owner = c.user_id == current_user.id
    in_window = c.created_at and (datetime.utcnow() - c.created_at) < _COMMENT_EDIT_WINDOW
    if not is_admin and not (is_owner and in_window):
        raise HTTPException(403, "Sem permissão para eliminar")
    c.deleted_at = datetime.utcnow()
    await db.commit()


# ────────────────────────────────────────────────────────────────────
# Anexos múltiplos
# ────────────────────────────────────────────────────────────────────

@router.post("/{id}/anexos", status_code=201)
async def upload_anexo(
    id: UUID,
    req: Request,
    file: UploadFile = File(...),
    titulo: str = Form(..., description="Título do ficheiro, ex: FR1234 ou FP5678"),
    tipo_fatura: str = Form(..., description="'proforma' ou 'recibo'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_assistente),
):
    import re
    await _get_movimento(db, id, current_user.company_id)
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(400, f"Tipo de ficheiro não suportado: {file.content_type}")
    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(400, "Ficheiro maior que 10 MB")

    titulo_norm = (titulo or "").strip().upper()
    if not re.match(r"^(FR|FP)[0-9A-Z\-/]+$", titulo_norm):
        raise HTTPException(400, "Título obrigatório no formato FRxxxx ou FPxxxx")

    tipo_norm = (tipo_fatura or "").strip().lower()
    if tipo_norm not in ("proforma", "recibo"):
        raise HTTPException(400, "Tipo de fatura inválido (use 'proforma' ou 'recibo')")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
    safe = f"mov_{id}_{uuid4().hex[:8]}.{ext}"
    file_key = f"movimentos/{safe}"

    storage = get_storage_provider()
    import io as _io
    await storage.upload(file_key, _io.BytesIO(content), content_type=file.content_type or "application/octet-stream")

    display_name = f"{titulo_norm}.{ext}" if ext != "bin" else titulo_norm
    a = MovimentoAnexoModel(
        movimento_id=id,
        company_id=current_user.company_id,
        file_path=file_key,
        file_name=display_name,
        mime_type=file.content_type,
        size_bytes=len(content),
        uploaded_by=current_user.id,
        tipo_fatura=tipo_norm,
    )
    db.add(a)
    await db.flush()
    # Movimento passa a 'fechado' (regra: 1+ anexo → fechado)
    from sqlalchemy import text as _t
    await db.execute(
        _t("UPDATE movimentos_financeiros SET estado_movimento = 'fechado', updated_at = NOW() WHERE id::text = :mid"),
        {"mid": str(id)},
    )
    await write_audit(
        db, current_user.id, current_user.company_id,
        "anexo_upload", "anexo", a.id,
        dados_novos={
            "movimento_id": str(id),
            "file_name": display_name,
            "titulo": titulo_norm,
            "tipo_fatura": tipo_norm,
            "size_bytes": len(content),
        },
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    await db.refresh(a)
    return {"id": str(a.id), "file_name": a.file_name, "file_path": a.file_path}


class EliminarAnexoDTO(BaseModel):
    motivo: str = Field(..., min_length=3, max_length=500)


@router.delete("/{id}/anexos/{aid}", status_code=204)
async def eliminar_anexo(
    id: UUID, aid: UUID,
    body: EliminarAnexoDTO,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_financeiro),
):
    r = await db.execute(select(MovimentoAnexoModel).where(MovimentoAnexoModel.id == aid))
    a = r.scalar_one_or_none()
    if not a or a.movimento_id != id or a.company_id != current_user.company_id:
        raise HTTPException(404, "Anexo não encontrado")
    if a.deleted_at:
        raise HTTPException(400, "Anexo já foi eliminado")
    snapshot = {
        "movimento_id": str(id),
        "file_name": a.file_name,
        "tipo_fatura": a.tipo_fatura,
    }
    a.deleted_at = datetime.utcnow()
    a.deleted_by = str(current_user.id)
    a.delete_reason = body.motivo.strip()
    # Se já não restarem anexos, voltar estado_movimento para pendente/criado consoante estado_pagamento
    from sqlalchemy import text as _t
    chk = await db.execute(
        _t("SELECT COUNT(*) FROM movimento_anexos WHERE movimento_id::text = :mid AND deleted_at IS NULL"),
        {"mid": str(id)},
    )
    if (chk.scalar_one() or 0) == 0:
        await db.execute(_t(
            "UPDATE movimentos_financeiros "
            "SET estado_movimento = CASE WHEN COALESCE(estado_pagamento,'') = '' THEN 'criado' ELSE 'pendente' END, "
            "updated_at = NOW() WHERE id::text = :mid"
        ), {"mid": str(id)})
    await write_audit(
        db, current_user.id, current_user.company_id,
        "anexo_eliminado", "anexo", a.id,
        dados_anteriores=snapshot,
        dados_novos={"motivo": body.motivo.strip()},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()


# ────────────────────────────────────────────────────────────────────
# Mudar estado com workflow
# ────────────────────────────────────────────────────────────────────

class MudarEstadoDTO(BaseModel):
    novo_estado: Literal["pendente", "pago", "pago_parcial", "pago_total", "cancelado", "devolvido"]
    motivo: Optional[str] = Field(None, max_length=500)
    comentario: Optional[str] = Field(None, max_length=500)


_ESTADOS_FECHADO = {"pago", "pago_total"}
_REQUER_MOTIVO = {"cancelado", "devolvido"}


@router.post("/{id}/mudar-estado")
async def mudar_estado(
    id: UUID,
    body: MudarEstadoDTO,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_financeiro),
):
    m = await _get_movimento(db, id, current_user.company_id)

    # Validar período fechado
    if m.data and await is_periodo_fechado(db, current_user.company_id, m.data):
        raise HTTPException(403, f"Período {m.data.year}-{m.data.month:02d} encontra-se fechado. Para reabrir, contacte o Administrador/a.")

    if body.novo_estado in _REQUER_MOTIVO and not (body.motivo and body.motivo.strip()):
        raise HTTPException(400, f"Motivo obrigatório para o estado '{body.novo_estado}'")

    estado_anterior = m.estado_pagamento
    if estado_anterior == body.novo_estado:
        return {"changed": False, "estado": estado_anterior}

    m.estado_pagamento = body.novo_estado
    # Calcular estado_movimento + closed_at/by
    if body.novo_estado in _ESTADOS_FECHADO:
        m.estado_movimento = "fechado"
        m.closed_at = datetime.utcnow()
        m.closed_by = current_user.id
    elif body.novo_estado == "pendente":
        m.estado_movimento = "pendente"
        m.closed_at = None
        m.closed_by = None
    elif body.novo_estado == "pago_parcial":
        m.estado_movimento = "pendente"
        m.closed_at = None
        m.closed_by = None
    else:
        m.estado_movimento = "criado"
        m.closed_at = None
        m.closed_by = None

    # Histórico
    motivo_full = (body.motivo or "").strip()
    if body.comentario and body.comentario.strip():
        motivo_full = (motivo_full + " · " if motivo_full else "") + body.comentario.strip()
    hist = MovimentoHistoricoModel(
        movimento_id=id,
        company_id=current_user.company_id,
        user_id=current_user.id,
        campo="estado_pagamento",
        valor_anterior=estado_anterior,
        valor_novo=body.novo_estado,
        observacao=motivo_full or None,
    )
    db.add(hist)

    # Comentário automático espelhado
    if motivo_full:
        com = MovimentoComentarioModel(
            movimento_id=id,
            company_id=current_user.company_id,
            user_id=current_user.id,
            texto=f"[Estado: {estado_anterior} → {body.novo_estado}] {motivo_full}",
        )
        db.add(com)

    await write_audit(
        db, current_user.id, current_user.company_id,
        "mudar_estado", "movimento", id,
        dados_anteriores={"estado_pagamento": estado_anterior},
        dados_novos={"estado_pagamento": body.novo_estado, "motivo": body.motivo, "comentario": body.comentario},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {
        "changed": True,
        "estado_pagamento": body.novo_estado,
        "estado_movimento": m.estado_movimento,
        "closed_at": m.closed_at.isoformat() if m.closed_at else None,
    }


__all__ = ["router"]
