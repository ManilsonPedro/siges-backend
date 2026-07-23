from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List, Optional
from datetime import datetime

from app.application.dtos import ClienteCreateDTO, ClienteUpdateDTO, ClienteResponseDTO
from app.infrastructure.database import get_db
from app.infrastructure.database.models import VendaModel
from app.infrastructure.repositories import ClienteRepository
from app.infrastructure.auth.dependencies import get_current_user
from app.infrastructure.audit import write_audit
from app.domain.entities import Cliente, User

router = APIRouter()


def _cli_dict(c) -> dict:
    return {
        "id": str(c.id),
        "nome": c.nome,
        "nif": c.nif,
        "telefone": c.telefone,
        "email": c.email,
        "endereco": c.endereco,
        "estado": c.estado,
        "fornecedor_id": str(c.fornecedor_id) if c.fornecedor_id else None,
    }


@router.get("", response_model=List[ClienteResponseDTO])
async def list_clientes(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    repo = ClienteRepository(db)
    return await repo.get_all(current_user.company_id)


# ─── Histórico Comercial e Conta Corrente ────────────────────────────
# Agregações reais sobre VendaModel/VendaPagamentoModel do próprio cliente
# — sem qualquer sync externo (ver PROMPT_SISTEMA_SIGES_SPRINTS.md, Sprint 1).
# Registadas antes de GET /{id} para não serem capturadas pelo path param.


class HistoricoClienteDTO(BaseModel):
    total_compras: int
    total_gasto: Decimal
    ultima_compra: Optional[datetime] = None
    produto_mais_comprado: Optional[str] = None
    qtd_produto_mais_comprado: Decimal = Decimal("0")
    ultima_fatura: Optional[str] = None


class HistoricoClienteResumoDTO(HistoricoClienteDTO):
    cliente_id: UUID
    cliente_nome: str


def _agregar_historico(vendas: List[VendaModel]) -> HistoricoClienteDTO:
    if not vendas:
        return HistoricoClienteDTO(total_compras=0, total_gasto=Decimal("0"))

    total_gasto = sum((Decimal(v.total_liquido) for v in vendas), Decimal("0"))

    qtd_por_produto: dict[str, Decimal] = {}
    for v in vendas:
        for ln in v.linhas:
            qtd_por_produto[ln.nome_snapshot] = qtd_por_produto.get(ln.nome_snapshot, Decimal("0")) + Decimal(ln.quantidade)
    produto_top = max(qtd_por_produto, key=qtd_por_produto.get) if qtd_por_produto else None

    ultima = vendas[0]  # vendas já vem ordenada por data desc
    return HistoricoClienteDTO(
        total_compras=len(vendas),
        total_gasto=total_gasto,
        ultima_compra=ultima.data,
        produto_mais_comprado=produto_top,
        qtd_produto_mais_comprado=qtd_por_produto.get(produto_top, Decimal("0")) if produto_top else Decimal("0"),
        ultima_fatura=ultima.numero_fatura_interna or ultima.numero_proforma,
    )


@router.get("/historico-comercial", response_model=List[HistoricoClienteResumoDTO])
async def historico_comercial_geral(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resumo de compras por cliente — só clientes com pelo menos uma venda concluída."""
    repo = ClienteRepository(db)
    clientes = await repo.get_all(current_user.company_id)

    r = await db.execute(
        select(VendaModel)
        .options(selectinload(VendaModel.linhas))
        .where(VendaModel.company_id == current_user.company_id)
        .where(VendaModel.estado == "concluida")
        .order_by(VendaModel.data.desc())
    )
    vendas_por_cliente: dict[str, List[VendaModel]] = {}
    for v in r.scalars().all():
        if v.cliente_id:
            vendas_por_cliente.setdefault(v.cliente_id, []).append(v)

    out: List[HistoricoClienteResumoDTO] = []
    for c in clientes:
        vendas = vendas_por_cliente.get(str(c.id))
        if not vendas:
            continue
        resumo = _agregar_historico(vendas)
        out.append(HistoricoClienteResumoDTO(cliente_id=c.id, cliente_nome=c.nome, **resumo.model_dump()))

    out.sort(key=lambda x: x.total_gasto, reverse=True)
    return out


@router.get("/{id}", response_model=ClienteResponseDTO)
async def get_cliente(id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    repo = ClienteRepository(db)
    c = await repo.get_by_id(id)
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(404, "Cliente não encontrado")
    return c


@router.post("", response_model=ClienteResponseDTO, status_code=201)
async def create_cliente(
    req: Request,
    body: ClienteCreateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = ClienteRepository(db)
    existing = await repo.get_by_nif(current_user.company_id, body.nif)
    if existing:
        raise HTTPException(409, "Cliente com este NIF já existe")
    entity = Cliente(
        company_id=current_user.company_id,
        nome=body.nome, nif=body.nif,
        telefone=body.telefone or "", email=body.email or "",
        endereco=body.endereco or "", estado=body.estado,
    )
    created = await repo.create(entity)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "criado", "cliente", created.id,
        dados_novos=_cli_dict(created),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return created


@router.put("/{id}", response_model=ClienteResponseDTO)
async def update_cliente(
    id: UUID,
    req: Request,
    body: ClienteUpdateDTO,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = ClienteRepository(db)
    c = await repo.get_by_id(id)
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(404, "Cliente não encontrado")
    dados_ant = _cli_dict(c)
    if body.nome is not None: c.nome = body.nome
    if body.nif is not None: c.nif = body.nif
    if body.telefone is not None: c.telefone = body.telefone
    if body.email is not None: c.email = body.email
    if body.endereco is not None: c.endereco = body.endereco
    if body.estado is not None: c.estado = body.estado
    c.updated_at = datetime.utcnow()
    updated = await repo.update(id, c)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "atualizado", "cliente", id,
        dados_anteriores=dados_ant,
        dados_novos=_cli_dict(updated),
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return updated


@router.delete("/{id}", status_code=204)
async def delete_cliente(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = ClienteRepository(db)
    c = await repo.get_by_id(id)
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(404, "Cliente não encontrado")
    dados_ant = _cli_dict(c)
    await repo.delete(id)
    await write_audit(
        db, current_user.id, current_user.company_id,
        "eliminado", "cliente", id,
        dados_anteriores=dados_ant,
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()


@router.post("/{id}/tornar-fornecedor", response_model=dict)
async def tornar_cliente_fornecedor(
    id: UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cria um Fornecedor espelho do Cliente e estabelece a ponte 1↔1."""
    from app.infrastructure.repositories import FornecedorRepository
    from app.domain.entities import Fornecedor as FornecedorEntity
    repo = ClienteRepository(db)
    c = await repo.get_by_id(id)
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(404, "Cliente não encontrado")
    if c.fornecedor_id:
        raise HTTPException(400, "Este cliente já está vinculado a um fornecedor")

    f_repo = FornecedorRepository(db)
    existente = await f_repo.get_by_nif(c.nif)
    if existente and existente.company_id == current_user.company_id:
        c.fornecedor_id = str(existente.id)
        existente.cliente_id = str(c.id)
        await f_repo.update(existente.id, existente)
        await repo.update(id, c)
        fornecedor_id = existente.id
    else:
        novo = FornecedorEntity(
            company_id=current_user.company_id, nome=c.nome, nif=c.nif,
            telefone=c.telefone or "", email=c.email or "", endereco=c.endereco or "",
            estado="ativo", cliente_id=str(c.id),
        )
        criado = await f_repo.create(novo)
        c.fornecedor_id = str(criado.id)
        await repo.update(id, c)
        fornecedor_id = criado.id

    await write_audit(
        db, current_user.id, current_user.company_id,
        "vinculado_fornecedor", "cliente", id,
        dados_novos={"fornecedor_id": str(fornecedor_id), "nome": c.nome, "nif": c.nif},
        ip_address=req.client.host if req.client else None,
    )
    await db.commit()
    return {"fornecedor_id": str(fornecedor_id), "cliente_id": str(id)}


async def _load_cliente_da_empresa(db: AsyncSession, id: UUID, current_user: User) -> Cliente:
    repo = ClienteRepository(db)
    c = await repo.get_by_id(id)
    if not c or c.company_id != current_user.company_id:
        raise HTTPException(404, "Cliente não encontrado")
    return c


@router.get("/{id}/historico", response_model=HistoricoClienteDTO)
async def historico_cliente(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _load_cliente_da_empresa(db, id, current_user)

    r = await db.execute(
        select(VendaModel)
        .options(selectinload(VendaModel.linhas))
        .where(VendaModel.company_id == current_user.company_id)
        .where(VendaModel.cliente_id == str(id))
        .where(VendaModel.estado == "concluida")
        .order_by(VendaModel.data.desc())
    )
    return _agregar_historico(list(r.scalars().all()))


class LancamentoContaCorrenteDTO(BaseModel):
    id: UUID
    data: datetime
    documento: str
    descricao: str
    debito: Decimal
    credito: Decimal
    saldo: Decimal


@router.get("/{id}/conta-corrente", response_model=List[LancamentoContaCorrenteDTO])
async def conta_corrente_cliente(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _load_cliente_da_empresa(db, id, current_user)

    r = await db.execute(
        select(VendaModel)
        .options(selectinload(VendaModel.pagamentos))
        .where(VendaModel.company_id == current_user.company_id)
        .where(VendaModel.cliente_id == str(id))
        .where(VendaModel.estado == "concluida")
        .order_by(VendaModel.data)
    )
    vendas = list(r.scalars().all())

    eventos: List[tuple] = []
    for v in vendas:
        doc = v.numero_fatura_interna or v.numero_proforma or str(v.id)[:8]
        eventos.append((v.data, v.id, doc, "Venda", Decimal(v.total_liquido), Decimal("0")))
        for p in v.pagamentos:
            eventos.append((p.data, p.id, doc, f"Pagamento ({p.forma})", Decimal("0"), Decimal(p.valor)))

    eventos.sort(key=lambda e: e[0])

    saldo = Decimal("0")
    lancamentos: List[LancamentoContaCorrenteDTO] = []
    for data, ev_id, doc, descricao, debito, credito in eventos:
        saldo += debito - credito
        lancamentos.append(LancamentoContaCorrenteDTO(
            id=ev_id, data=data, documento=doc, descricao=descricao,
            debito=debito, credito=credito, saldo=saldo,
        ))
    return lancamentos


__all__ = ["router"]
