from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from uuid import UUID, uuid4
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from typing import Optional, Literal

from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    MovimentoPagamentoModel, MovimentoFinanceiroModel, UserModel,
)
from app.infrastructure.auth.dependencies import get_current_user, require_financeiro
from app.infrastructure.audit import write_audit
from app.domain.entities import User

router = APIRouter()


class PagamentoCreateDTO(BaseModel):
    valor: Decimal = Field(..., gt=0)
    data: Optional[datetime] = None
    fundo_tipo: Literal["BCS", "BFA"] = "BCS"
    observacao: Optional[str] = Field(None, max_length=500)


def _to_dict(p: MovimentoPagamentoModel, user_name: Optional[str] = None) -> dict:
    return {
        "id": str(p.id),
        "movimento_id": str(p.movimento_id),
        "valor": float(p.valor),
        "data": p.data.isoformat() if p.data else None,
        "fundo_tipo": p.fundo_tipo,
        "observacao": p.observacao,
        "created_by_name": user_name,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


async def _calcular_estado(db: AsyncSession, movimento_id, valor_total: Decimal, tipo_movimento: str) -> str:
    """Calcula estado_pagamento com base na soma dos sub-pagamentos."""
    r = await db.execute(
        select(func.coalesce(func.sum(MovimentoPagamentoModel.valor), 0))
        .where(and_(
            MovimentoPagamentoModel.movimento_id == movimento_id,
            MovimentoPagamentoModel.deleted_at == None,
        ))
    )
    pago = Decimal(str(r.scalar_one() or 0))

    if tipo_movimento == "saida":
        if pago >= valor_total:
            return "pago"
        elif pago > 0:
            return "pago"  # saídas: parcial não é estado natural; mantém "pago" mas guarda histórico
        else:
            return "pendente"
    else:  # entrada
        if pago >= valor_total:
            return "pago_total"
        elif pago > 0:
            return "pago_parcial"
        else:
            return "pendente"


@router.get("/{movimento_id}")
async def listar_pagamentos(
    movimento_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista todos os sub-pagamentos de um movimento."""
    # Verifica que o movimento pertence à empresa
    rm = await db.execute(select(MovimentoFinanceiroModel).where(
        MovimentoFinanceiroModel.id == movimento_id,
    ))
    mov = rm.scalar_one_or_none()
    if not mov or mov.company_id != current_user.company_id:
        raise HTTPException(404, "Movimento não encontrado")

    r = await db.execute(
        select(MovimentoPagamentoModel, UserModel.full_name)
        .outerjoin(UserModel, MovimentoPagamentoModel.created_by == UserModel.id)
        .where(and_(
            MovimentoPagamentoModel.movimento_id == movimento_id,
            MovimentoPagamentoModel.deleted_at == None,
        ))
        .order_by(MovimentoPagamentoModel.data.desc())
    )
    pagamentos = [_to_dict(row[0], row[1]) for row in r.all()]

    # Calcula totais
    total_pago = sum(p["valor"] for p in pagamentos)
    valor_movimento = float(mov.valor)
    return {
        "movimento_id": str(movimento_id),
        "valor_movimento": valor_movimento,
        "total_pago": total_pago,
        "saldo_em_divida": max(0.0, valor_movimento - total_pago),
        "pagamentos": pagamentos,
    }


@router.post("/{movimento_id}", status_code=status.HTTP_201_CREATED)
async def adicionar_pagamento(
    movimento_id: UUID,
    body: PagamentoCreateDTO,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_financeiro),
):
    """Regista um sub-pagamento parcial."""
    rm = await db.execute(select(MovimentoFinanceiroModel).where(
        MovimentoFinanceiroModel.id == movimento_id,
    ))
    mov = rm.scalar_one_or_none()
    if not mov or mov.company_id != current_user.company_id:
        raise HTTPException(404, "Movimento não encontrado")
    if mov.deleted_at is not None:
        raise HTTPException(400, "Movimento eliminado — restaure-o primeiro")

    valor_mov = Decimal(str(mov.valor))

    # Soma actual
    r = await db.execute(
        select(func.coalesce(func.sum(MovimentoPagamentoModel.valor), 0))
        .where(and_(
            MovimentoPagamentoModel.movimento_id == movimento_id,
            MovimentoPagamentoModel.deleted_at == None,
        ))
    )
    pago_actual = Decimal(str(r.scalar_one() or 0))
    saldo = valor_mov - pago_actual
    if body.valor > saldo:
        raise HTTPException(400, f"Valor excede o saldo em dívida ({float(saldo):.2f} Kz).")

    p = MovimentoPagamentoModel(
        movimento_id=movimento_id,
        company_id=current_user.company_id,
        valor=body.valor,
        data=body.data or datetime.utcnow(),
        fundo_tipo=body.fundo_tipo,
        observacao=body.observacao,
        created_by=current_user.id,
    )
    db.add(p)
    await db.flush()

    # Recalcula estado do movimento
    novo_estado = await _calcular_estado(db, movimento_id, valor_mov, mov.tipo_movimento)
    if mov.estado_pagamento != novo_estado:
        mov.estado_pagamento = novo_estado
        if novo_estado in ("pago", "pago_total"):
            mov.estado_movimento = "fechado"
        elif novo_estado in ("pago_parcial", "pendente"):
            mov.estado_movimento = "pendente"

    await write_audit(
        db, current_user.id, current_user.company_id,
        "pagamento_parcial", "movimento", movimento_id,
        dados_novos={"valor": float(body.valor), "fundo_tipo": body.fundo_tipo, "novo_estado": novo_estado},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    await db.refresh(p)
    return _to_dict(p, current_user.full_name)


@router.delete("/{movimento_id}/{pagamento_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_pagamento(
    movimento_id: UUID,
    pagamento_id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_financeiro),
):
    """Soft-delete de um sub-pagamento e recalcula o estado."""
    r = await db.execute(select(MovimentoPagamentoModel).where(
        MovimentoPagamentoModel.id == pagamento_id,
    ))
    p = r.scalar_one_or_none()
    if not p or p.company_id != current_user.company_id or p.movimento_id != movimento_id:
        raise HTTPException(404, "Pagamento não encontrado")
    if p.deleted_at:
        raise HTTPException(400, "Pagamento já eliminado")

    p.deleted_at = datetime.utcnow()

    rm = await db.execute(select(MovimentoFinanceiroModel).where(
        MovimentoFinanceiroModel.id == movimento_id,
    ))
    mov = rm.scalar_one_or_none()
    if mov:
        valor_mov = Decimal(str(mov.valor))
        novo_estado = await _calcular_estado(db, movimento_id, valor_mov, mov.tipo_movimento)
        if mov.estado_pagamento != novo_estado:
            mov.estado_pagamento = novo_estado
            mov.estado_movimento = "fechado" if novo_estado in ("pago", "pago_total") else "pendente"

    await write_audit(
        db, current_user.id, current_user.company_id,
        "pagamento_eliminado", "movimento", movimento_id,
        dados_anteriores={"valor": float(p.valor)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()


__all__ = ["router"]
