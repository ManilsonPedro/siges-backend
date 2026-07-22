"""Devoluções de vendas (domínio Comércio / POS).

Devolução gera StockMovimento de entrada por linha (excepto motivo
'danificado', que vai para ajuste negativo com motivo) via
app.domain.services.stock_service — nunca escreve stock directamente.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import User
from app.domain.services import stock_service
from app.infrastructure.audit import write_audit
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    DevolucaoLinhaModel,
    DevolucaoModel,
    VendaLinhaModel,
    VendaModel,
)


router = APIRouter()


class DevolucaoLinhaInDTO(BaseModel):
    produto_id: UUID
    quantidade: Decimal = Field(..., gt=0)
    motivo: str = Field(default="normal", pattern="^(normal|danificado)$")


class DevolucaoCreateDTO(BaseModel):
    venda_id: UUID
    linhas: List[DevolucaoLinhaInDTO] = Field(..., min_length=1)
    forma_devolucao: str = Field(..., pattern="^(numerario|credito_cliente|troca)$")


class DevolucaoLinhaResponseDTO(BaseModel):
    id: UUID
    produto_id: UUID
    quantidade: Decimal
    motivo: str

    class Config:
        from_attributes = True


class DevolucaoResponseDTO(BaseModel):
    id: UUID
    company_id: UUID
    venda_id: UUID
    valor_devolvido: Decimal
    forma_devolucao: str
    data: datetime
    linhas: List[DevolucaoLinhaResponseDTO] = []

    class Config:
        from_attributes = True


async def _to_response(db: AsyncSession, d: DevolucaoModel) -> DevolucaoResponseDTO:
    lr = await db.execute(select(DevolucaoLinhaModel).where(DevolucaoLinhaModel.devolucao_id == d.id))
    dto = DevolucaoResponseDTO.model_validate(d)
    dto.linhas = [DevolucaoLinhaResponseDTO.model_validate(l) for l in lr.scalars().all()]
    return dto


@router.get("", response_model=List[DevolucaoResponseDTO])
async def list_devolucoes(
    venda_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("caixa.ver")),
):
    stmt = select(DevolucaoModel).where(DevolucaoModel.company_id == current_user.company_id)
    if venda_id:
        stmt = stmt.where(DevolucaoModel.venda_id == venda_id)
    stmt = stmt.order_by(DevolucaoModel.data.desc())
    r = await db.execute(stmt)
    return [await _to_response(db, d) for d in r.scalars().all()]


@router.post("", response_model=DevolucaoResponseDTO, status_code=201)
async def create_devolucao(
    req: Request,
    body: DevolucaoCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("caixa.processar_devolucao")),
):
    vr = await db.execute(select(VendaModel).where(VendaModel.id == body.venda_id))
    venda = vr.scalar_one_or_none()
    if not venda or venda.company_id != current_user.company_id:
        raise HTTPException(404, "Venda não encontrada")
    if venda.estado != "concluida":
        raise HTTPException(400, "Só é possível devolver linhas de vendas concluídas")

    lr = await db.execute(select(VendaLinhaModel).where(VendaLinhaModel.venda_id == venda.id))
    linhas_venda = {l.produto_id: l for l in lr.scalars().all()}

    valor_devolvido = Decimal("0")
    dev = DevolucaoModel(
        id=uuid4(), company_id=current_user.company_id, venda_id=venda.id,
        valor_devolvido=Decimal("0"), forma_devolucao=body.forma_devolucao,
        responsavel_id=current_user.id,
    )
    db.add(dev)
    await db.flush()

    for linha_in in body.linhas:
        venda_linha = linhas_venda.get(linha_in.produto_id)
        if not venda_linha:
            raise HTTPException(400, f"Produto {linha_in.produto_id} não faz parte desta venda")
        if linha_in.quantidade > Decimal(venda_linha.quantidade):
            raise HTTPException(400, f"Quantidade a devolver excede a quantidade vendida para {venda_linha.sku_snapshot}")

        db.add(DevolucaoLinhaModel(
            id=uuid4(), devolucao_id=dev.id, produto_id=linha_in.produto_id,
            quantidade=linha_in.quantidade, motivo=linha_in.motivo,
        ))

        preco_unit_com_iva = Decimal(venda_linha.subtotal) / Decimal(venda_linha.quantidade)
        valor_devolvido += (preco_unit_com_iva * linha_in.quantidade).quantize(Decimal("0.01"))

        if linha_in.motivo == "normal":
            # Produto em condições de venda: volta a entrar no stock disponível.
            await stock_service.registar_movimento(
                db, company_id=current_user.company_id, produto_id=linha_in.produto_id,
                tipo="entrada_ajuste", quantidade=linha_in.quantidade,
                armazem_destino_id=venda.armazem_id, motivo=f"Devolução de venda {venda.id}",
                created_by=current_user.id,
                documento_ref_tipo="devolucao", documento_ref_id=str(dev.id),
            )
        # Se motivo == "danificado": não gera movimento de stock — o produto
        # não reentra no stock disponível (já tinha saído na venda original).

    dev.valor_devolvido = valor_devolvido
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criada", "devolucao", dev.id,
        dados_novos={"venda_id": str(venda.id), "valor_devolvido": str(valor_devolvido)},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return await _to_response(db, dev)


__all__ = ["router"]
