from uuid import UUID, uuid4
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, or_
from app.domain.entities import User, Fornecedor, Cliente, Conceito, Fundo, MovimentoFinanceiro, AuditLog
from app.domain.repositories import (
    IUserRepository,
    IFornecedorRepository,
    IConceptoRepository,
    IFundoRepository,
    IMovimentoRepository,
    IAuditLogRepository,
)
from app.infrastructure.database.models import (
    UserModel,
    FornecedorModel,
    ClienteModel,
    ConceptoModel,
    FundoModel,
    MovimentoFinanceiroModel,
    MovimentoHistoricoModel,
    AuditLogModel,
)


class UserRepository(IUserRepository):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id: UUID) -> Optional[User]:
        result = await self.db.execute(select(UserModel).where(UserModel.id == id))
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(select(UserModel).where(UserModel.email == email))
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_all(self, skip: int = 0, limit: int = 500) -> List[User]:
        result = await self.db.execute(select(UserModel).offset(skip).limit(limit))
        return [self._to_entity(m) for m in result.scalars().all()]

    async def create(self, entity: User) -> User:
        model = UserModel(
            id=str(entity.id),
            company_id=str(entity.company_id),
            email=entity.email,
            hashed_password=entity.hashed_password,
            full_name=entity.full_name,
            is_active=entity.is_active,
            must_change_password=entity.must_change_password,
        )
        self.db.add(model)
        await self.db.flush()
        return self._to_entity(model)

    async def update(self, id: UUID, entity: User) -> Optional[User]:
        result = await self.db.execute(select(UserModel).where(UserModel.id == id))
        model = result.scalar_one_or_none()
        if not model:
            return None
        model.email = entity.email
        model.full_name = entity.full_name
        model.is_active = entity.is_active
        model.must_change_password = entity.must_change_password
        if entity.hashed_password:
            model.hashed_password = entity.hashed_password
        await self.db.flush()
        return self._to_entity(model)

    async def delete(self, id: UUID) -> bool:
        result = await self.db.execute(select(UserModel).where(UserModel.id == id))
        model = result.scalar_one_or_none()
        if not model:
            return False
        await self.db.delete(model)
        await self.db.flush()
        return True

    @staticmethod
    def _to_entity(model: UserModel) -> User:
        u = User(
            id=model.id,
            company_id=model.company_id,
            email=model.email,
            hashed_password=model.hashed_password,
            full_name=model.full_name,
            is_active=model.is_active,
            must_change_password=getattr(model, "must_change_password", False) or False,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )
        # Carry extra DB columns that exist on the model but not the base entity dataclass
        try:
            u.is_superadmin = bool(model.is_superadmin)
        except Exception:
            u.is_superadmin = False
        u.grupo_id = getattr(model, "grupo_id", None)
        return u


class FornecedorRepository(IFornecedorRepository):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id: UUID) -> Optional[Fornecedor]:
        result = await self.db.execute(
            select(FornecedorModel).where(FornecedorModel.id == id, FornecedorModel.deleted_at == None)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_nif(self, nif: str) -> Optional[Fornecedor]:
        result = await self.db.execute(
            select(FornecedorModel).where(FornecedorModel.nif == nif, FornecedorModel.deleted_at == None)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_company(self, company_id: UUID) -> List[Fornecedor]:
        result = await self.db.execute(
            select(FornecedorModel).where(
                FornecedorModel.company_id == company_id,
                FornecedorModel.deleted_at == None,
            )
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_all(self, company_id: UUID, skip: int = 0, limit: int = 100) -> List[Fornecedor]:
        result = await self.db.execute(
            select(FornecedorModel)
            .where(FornecedorModel.company_id == company_id, FornecedorModel.deleted_at == None)
            .offset(skip)
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count(self, company_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(FornecedorModel.id)).where(
                FornecedorModel.company_id == company_id, FornecedorModel.deleted_at == None
            )
        )
        return result.scalar_one()

    async def create(self, entity: Fornecedor) -> Fornecedor:
        model = FornecedorModel(
            id=entity.id,
            company_id=entity.company_id,
            nome=entity.nome,
            nif=entity.nif,
            telefone=entity.telefone,
            email=entity.email,
            endereco=entity.endereco,
            estado=entity.estado,
            tipo_pessoa=entity.tipo_pessoa,
            cliente_id=entity.cliente_id,
        )
        self.db.add(model)
        await self.db.flush()
        return self._to_entity(model)

    async def update(self, id: UUID, entity: Fornecedor) -> Optional[Fornecedor]:
        result = await self.db.execute(select(FornecedorModel).where(FornecedorModel.id == id))
        model = result.scalar_one_or_none()
        if not model:
            return None
        model.nome = entity.nome
        model.nif = entity.nif
        model.telefone = entity.telefone
        model.email = entity.email
        model.endereco = entity.endereco
        model.estado = entity.estado
        if entity.tipo_pessoa is not None:
            model.tipo_pessoa = entity.tipo_pessoa
        if entity.cliente_id is not None:
            model.cliente_id = entity.cliente_id
        model.updated_at = datetime.utcnow()
        await self.db.flush()
        return self._to_entity(model)

    async def delete(self, id: UUID) -> bool:
        result = await self.db.execute(select(FornecedorModel).where(FornecedorModel.id == id))
        model = result.scalar_one_or_none()
        if not model:
            return False
        model.deleted_at = datetime.utcnow()
        await self.db.flush()
        return True

    @staticmethod
    def _to_entity(model: FornecedorModel) -> Fornecedor:
        return Fornecedor(
            id=model.id,
            company_id=model.company_id,
            nome=model.nome,
            nif=model.nif,
            telefone=model.telefone,
            email=model.email,
            endereco=model.endereco,
            estado=model.estado,
            tipo_pessoa=model.tipo_pessoa,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
            cliente_id=model.cliente_id,
        )


class ClienteRepository:
    """Repositório de Clientes (espelho de FornecedorRepository)."""
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id: UUID) -> Optional[Cliente]:
        r = await self.db.execute(select(ClienteModel).where(ClienteModel.id == id, ClienteModel.deleted_at == None))
        m = r.scalar_one_or_none()
        return self._to_entity(m) if m else None

    async def get_by_nif(self, company_id: UUID, nif: str) -> Optional[Cliente]:
        r = await self.db.execute(
            select(ClienteModel).where(ClienteModel.company_id == company_id, ClienteModel.nif == nif, ClienteModel.deleted_at == None)
        )
        m = r.scalar_one_or_none()
        return self._to_entity(m) if m else None

    async def get_all(self, company_id: UUID) -> List[Cliente]:
        r = await self.db.execute(
            select(ClienteModel).where(ClienteModel.company_id == company_id, ClienteModel.deleted_at == None)
        )
        return [self._to_entity(m) for m in r.scalars().all()]

    async def create(self, entity: Cliente) -> Cliente:
        m = ClienteModel(
            id=entity.id, company_id=entity.company_id, nome=entity.nome, nif=entity.nif,
            telefone=entity.telefone, email=entity.email, endereco=entity.endereco,
            estado=entity.estado, fornecedor_id=entity.fornecedor_id,
        )
        self.db.add(m)
        await self.db.flush()
        return self._to_entity(m)

    async def update(self, id: UUID, entity: Cliente) -> Optional[Cliente]:
        r = await self.db.execute(select(ClienteModel).where(ClienteModel.id == id))
        m = r.scalar_one_or_none()
        if not m:
            return None
        m.nome = entity.nome; m.nif = entity.nif; m.telefone = entity.telefone
        m.email = entity.email; m.endereco = entity.endereco; m.estado = entity.estado
        m.fornecedor_id = entity.fornecedor_id
        m.updated_at = datetime.utcnow()
        await self.db.flush()
        return self._to_entity(m)

    async def delete(self, id: UUID) -> bool:
        r = await self.db.execute(select(ClienteModel).where(ClienteModel.id == id))
        m = r.scalar_one_or_none()
        if not m:
            return False
        m.deleted_at = datetime.utcnow()
        await self.db.flush()
        return True

    @staticmethod
    def _to_entity(model: ClienteModel) -> Cliente:
        return Cliente(
            id=model.id, company_id=model.company_id, nome=model.nome, nif=model.nif,
            telefone=model.telefone or "", email=model.email or "", endereco=model.endereco or "",
            estado=model.estado or "ativo",
            created_at=model.created_at, updated_at=model.updated_at, deleted_at=model.deleted_at,
            fornecedor_id=model.fornecedor_id,
        )


class ConceptoRepository(IConceptoRepository):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id: UUID) -> Optional[Conceito]:
        result = await self.db.execute(
            select(ConceptoModel).where(ConceptoModel.id == id, ConceptoModel.deleted_at == None)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_company(self, company_id: UUID) -> List[Conceito]:
        result = await self.db.execute(
            select(ConceptoModel).where(
                ConceptoModel.company_id == company_id,
                ConceptoModel.deleted_at == None,
            )
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_all(self, company_id: UUID, skip: int = 0, limit: int = 100) -> List[Conceito]:
        result = await self.db.execute(
            select(ConceptoModel)
            .where(ConceptoModel.company_id == company_id, ConceptoModel.deleted_at == None)
            .offset(skip)
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count(self, company_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count(ConceptoModel.id)).where(
                ConceptoModel.company_id == company_id, ConceptoModel.deleted_at == None
            )
        )
        return result.scalar_one()

    async def create(self, entity: Conceito) -> Conceito:
        model = ConceptoModel(
            id=entity.id,
            company_id=entity.company_id,
            nome=entity.nome,
            descricao=entity.descricao,
            estado=entity.estado,
        )
        self.db.add(model)
        await self.db.flush()
        return self._to_entity(model)

    async def update(self, id: UUID, entity: Conceito) -> Optional[Conceito]:
        result = await self.db.execute(select(ConceptoModel).where(ConceptoModel.id == id))
        model = result.scalar_one_or_none()
        if not model:
            return None
        model.nome = entity.nome
        model.descricao = entity.descricao
        model.estado = entity.estado
        model.updated_at = datetime.utcnow()
        await self.db.flush()
        return self._to_entity(model)

    async def delete(self, id: UUID) -> bool:
        result = await self.db.execute(select(ConceptoModel).where(ConceptoModel.id == id))
        model = result.scalar_one_or_none()
        if not model:
            return False
        model.deleted_at = datetime.utcnow()
        await self.db.flush()
        return True

    @staticmethod
    def _to_entity(model: ConceptoModel) -> Conceito:
        return Conceito(
            id=model.id,
            company_id=model.company_id,
            nome=model.nome,
            descricao=model.descricao,
            estado=model.estado,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )


class FundoRepository(IFundoRepository):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_company(self, company_id: UUID) -> Optional[Fundo]:
        result = await self.db.execute(
            select(FundoModel).where(FundoModel.company_id == company_id)
        )
        model = result.scalars().first()
        return self._to_entity(model) if model else None

    async def get_by_company_and_tipo(self, company_id: UUID, tipo: str) -> Optional[Fundo]:
        result = await self.db.execute(
            select(FundoModel)
            .where(FundoModel.company_id == company_id, FundoModel.tipo == tipo)
            .limit(1)
        )
        model = result.scalars().first()
        return self._to_entity(model) if model else None

    async def get_by_id(self, id: UUID) -> Optional[Fundo]:
        result = await self.db.execute(select(FundoModel).where(FundoModel.id == id))
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_all(self, skip: int = 0, limit: int = 100) -> List[Fundo]:
        result = await self.db.execute(select(FundoModel).offset(skip).limit(limit))
        return [self._to_entity(m) for m in result.scalars().all()]

    async def create(self, entity: Fundo) -> Fundo:
        model = FundoModel(
            id=entity.id,
            company_id=entity.company_id,
            tipo=entity.tipo,
            data=entity.data or datetime.utcnow(),
            descricao=entity.descricao,
            valor_disponivel=entity.valor_disponivel,
            acumulado=entity.acumulado,
            saldo_atual=entity.saldo_atual,
            observacao=entity.observacao,
        )
        self.db.add(model)
        await self.db.flush()
        return self._to_entity(model)

    async def update(self, id: UUID, entity: Fundo) -> Optional[Fundo]:
        result = await self.db.execute(select(FundoModel).where(FundoModel.id == id))
        model = result.scalar_one_or_none()
        if not model:
            return None
        model.valor_disponivel = entity.valor_disponivel
        model.acumulado = entity.acumulado
        model.saldo_atual = entity.saldo_atual
        model.descricao = entity.descricao
        model.observacao = entity.observacao
        model.updated_at = datetime.utcnow()
        await self.db.flush()
        return self._to_entity(model)

    async def update_saldos(self, company_id: UUID, acumulado: Decimal, saldo_atual: Decimal) -> Optional[Fundo]:
        result = await self.db.execute(
            select(FundoModel).where(FundoModel.company_id == company_id)
        )
        model = result.scalars().first()
        if not model:
            return None
        model.acumulado = acumulado
        model.saldo_atual = saldo_atual
        model.updated_at = datetime.utcnow()
        await self.db.flush()
        return self._to_entity(model)

    async def update_saldos_by_tipo(self, company_id: UUID, tipo: str, acumulado: Decimal, saldo_atual: Decimal) -> None:
        result = await self.db.execute(
            select(FundoModel).where(FundoModel.company_id == company_id, FundoModel.tipo == tipo)
        )
        model = result.scalar_one_or_none()
        if model:
            model.acumulado = acumulado
            model.saldo_atual = saldo_atual
            model.updated_at = datetime.utcnow()
            await self.db.flush()

    async def delete(self, id: UUID) -> bool:
        result = await self.db.execute(select(FundoModel).where(FundoModel.id == id))
        model = result.scalar_one_or_none()
        if not model:
            return False
        await self.db.delete(model)
        await self.db.flush()
        return True

    @staticmethod
    def _to_entity(model: FundoModel) -> Fundo:
        return Fundo(
            id=model.id,
            company_id=model.company_id,
            tipo=getattr(model, "tipo", "BCS") or "BCS",
            data=model.data,
            descricao=model.descricao,
            valor_disponivel=model.valor_disponivel,
            acumulado=model.acumulado,
            saldo_atual=model.saldo_atual,
            observacao=model.observacao,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class MovimentoRepository(IMovimentoRepository):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, id: UUID) -> Optional[MovimentoFinanceiro]:
        result = await self.db.execute(
            select(MovimentoFinanceiroModel).where(
                MovimentoFinanceiroModel.id == id,
                MovimentoFinanceiroModel.deleted_at == None,
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_all(
        self,
        company_id: UUID,
        skip: int = 0,
        limit: int = 10,
        fornecedor_id: Optional[UUID] = None,
        conceito_id: Optional[UUID] = None,
        tipo_movimento: Optional[str] = None,
        estado_pagamento: Optional[str] = None,
        estado_movimento: Optional[str] = None,
        data_inicio: Optional[datetime] = None,
        data_fim: Optional[datetime] = None,
    ) -> List[MovimentoFinanceiro]:
        filters = [
            MovimentoFinanceiroModel.company_id == company_id,
            MovimentoFinanceiroModel.deleted_at == None,
        ]
        if fornecedor_id:
            filters.append(MovimentoFinanceiroModel.fornecedor_id == fornecedor_id)
        if conceito_id:
            filters.append(MovimentoFinanceiroModel.conceito_id == conceito_id)
        if tipo_movimento:
            filters.append(MovimentoFinanceiroModel.tipo_movimento == tipo_movimento)
        if estado_pagamento:
            filters.append(MovimentoFinanceiroModel.estado_pagamento == estado_pagamento)
        if estado_movimento:
            filters.append(MovimentoFinanceiroModel.estado_movimento == estado_movimento)
        if data_inicio:
            filters.append(MovimentoFinanceiroModel.data >= data_inicio)
        if data_fim:
            filters.append(MovimentoFinanceiroModel.data <= data_fim)

        result = await self.db.execute(
            select(MovimentoFinanceiroModel)
            .where(and_(*filters))
            .order_by(MovimentoFinanceiroModel.data.desc())
            .offset(skip)
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count(
        self,
        company_id: UUID,
        fornecedor_id: Optional[UUID] = None,
        conceito_id: Optional[UUID] = None,
        tipo_movimento: Optional[str] = None,
        estado_pagamento: Optional[str] = None,
        estado_movimento: Optional[str] = None,
        data_inicio: Optional[datetime] = None,
        data_fim: Optional[datetime] = None,
    ) -> int:
        filters = [
            MovimentoFinanceiroModel.company_id == company_id,
            MovimentoFinanceiroModel.deleted_at == None,
        ]
        if fornecedor_id:
            filters.append(MovimentoFinanceiroModel.fornecedor_id == fornecedor_id)
        if conceito_id:
            filters.append(MovimentoFinanceiroModel.conceito_id == conceito_id)
        if tipo_movimento:
            filters.append(MovimentoFinanceiroModel.tipo_movimento == tipo_movimento)
        if estado_pagamento:
            filters.append(MovimentoFinanceiroModel.estado_pagamento == estado_pagamento)
        if estado_movimento:
            filters.append(MovimentoFinanceiroModel.estado_movimento == estado_movimento)
        if data_inicio:
            filters.append(MovimentoFinanceiroModel.data >= data_inicio)
        if data_fim:
            filters.append(MovimentoFinanceiroModel.data <= data_fim)

        result = await self.db.execute(
            select(func.count(MovimentoFinanceiroModel.id)).where(and_(*filters))
        )
        return result.scalar_one()

    async def sum_by_tipo(self, company_id: UUID, tipo: str, estado: Optional[str] = "pago", fundo_tipo: Optional[str] = None) -> Decimal:
        filters = [
            MovimentoFinanceiroModel.company_id == company_id,
            MovimentoFinanceiroModel.tipo_movimento == tipo,
            MovimentoFinanceiroModel.deleted_at == None,
        ]
        if estado is not None:
            filters.append(MovimentoFinanceiroModel.estado_pagamento == estado)
        if fundo_tipo:
            filters.append(MovimentoFinanceiroModel.fundo_tipo == fundo_tipo)
        result = await self.db.execute(
            select(func.coalesce(func.sum(MovimentoFinanceiroModel.valor), 0)).where(and_(*filters))
        )
        return result.scalar_one()

    async def create(self, entity: MovimentoFinanceiro) -> MovimentoFinanceiro:
        model = MovimentoFinanceiroModel(
            id=entity.id,
            company_id=entity.company_id,
            data=entity.data or datetime.utcnow(),
            fornecedor_id=entity.fornecedor_id,
            cliente_id=entity.cliente_id,
            conceito_id=entity.conceito_id,
            fatura_proforma=entity.fatura_proforma,
            valor=entity.valor,
            fatura_recibo=entity.fatura_recibo,
            comprovativo_pagamento=entity.comprovativo_pagamento,
            observacoes=entity.observacoes,
            tipo_movimento=entity.tipo_movimento,
            estado_pagamento=entity.estado_pagamento or "pendente",
            estado_movimento=entity.estado_movimento or "criado",
            fundo_tipo=entity.fundo_tipo or "BCS",
            codigo=entity.codigo,
            created_by=entity.created_by,
        )
        self.db.add(model)
        await self.db.flush()
        await self.db.refresh(model)
        return self._to_entity(model)

    async def update(self, id: UUID, entity: MovimentoFinanceiro) -> Optional[MovimentoFinanceiro]:
        result = await self.db.execute(select(MovimentoFinanceiroModel).where(MovimentoFinanceiroModel.id == id))
        model = result.scalar_one_or_none()
        if not model:
            return None
        if entity.data is not None:
            model.data = entity.data
        if entity.fornecedor_id is not None:
            model.fornecedor_id = entity.fornecedor_id
        if entity.cliente_id is not None:
            model.cliente_id = entity.cliente_id
        if entity.conceito_id is not None:
            model.conceito_id = entity.conceito_id
        if entity.valor is not None:
            model.valor = entity.valor
        if entity.tipo_movimento is not None:
            model.tipo_movimento = entity.tipo_movimento
        if entity.estado_pagamento is not None:
            model.estado_pagamento = entity.estado_pagamento
        if entity.fatura_proforma is not None:
            model.fatura_proforma = entity.fatura_proforma
        if entity.fatura_recibo is not None:
            model.fatura_recibo = entity.fatura_recibo
        if entity.observacoes is not None:
            model.observacoes = entity.observacoes
        if entity.comprovativo_pagamento is not None:
            model.comprovativo_pagamento = entity.comprovativo_pagamento
        if entity.fundo_tipo and entity.fundo_tipo in ("BCS", "BFA"):
            model.fundo_tipo = entity.fundo_tipo
        if entity.estado_movimento:
            model.estado_movimento = entity.estado_movimento
        model.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(model)
        return self._to_entity(model)

    async def delete(self, id: UUID) -> bool:
        result = await self.db.execute(select(MovimentoFinanceiroModel).where(MovimentoFinanceiroModel.id == id))
        model = result.scalar_one_or_none()
        if not model:
            return False
        model.deleted_at = datetime.utcnow()
        await self.db.flush()
        return True

    async def get_by_company(self, company_id: UUID, skip: int = 0, limit: int = 100) -> List[MovimentoFinanceiro]:
        return await self.get_all(company_id, skip=skip, limit=limit)

    async def get_by_fornecedor(self, fornecedor_id: UUID) -> List[MovimentoFinanceiro]:
        result = await self.db.execute(
            select(MovimentoFinanceiroModel).where(
                MovimentoFinanceiroModel.fornecedor_id == fornecedor_id,
                MovimentoFinanceiroModel.deleted_at == None,
            )
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_by_conceito(self, conceito_id: UUID) -> List[MovimentoFinanceiro]:
        result = await self.db.execute(
            select(MovimentoFinanceiroModel).where(
                MovimentoFinanceiroModel.conceito_id == conceito_id,
                MovimentoFinanceiroModel.deleted_at == None,
            )
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_dashboard_stats(self, company_id: UUID) -> dict:
        total_pagos = await self.sum_by_tipo(company_id, "saida", "pago")
        total_pendentes_result = await self.db.execute(
            select(func.count(MovimentoFinanceiroModel.id)).where(
                MovimentoFinanceiroModel.company_id == company_id,
                MovimentoFinanceiroModel.estado_pagamento == "pendente",
                MovimentoFinanceiroModel.deleted_at == None,
            )
        )
        total_pagos_result = await self.db.execute(
            select(func.count(MovimentoFinanceiroModel.id)).where(
                MovimentoFinanceiroModel.company_id == company_id,
                MovimentoFinanceiroModel.estado_pagamento == "pago",
                MovimentoFinanceiroModel.deleted_at == None,
            )
        )
        return {
            "total_saidas_pagas": total_pagos,
            "count_pendentes": total_pendentes_result.scalar_one(),
            "count_pagos": total_pagos_result.scalar_one(),
        }

    @staticmethod
    def _to_entity(model: MovimentoFinanceiroModel) -> MovimentoFinanceiro:
        return MovimentoFinanceiro(
            id=model.id,
            company_id=model.company_id,
            data=model.data,
            fornecedor_id=model.fornecedor_id,
            cliente_id=getattr(model, "cliente_id", None),
            conceito_id=model.conceito_id,
            fatura_proforma=model.fatura_proforma,
            valor=model.valor,
            fatura_recibo=model.fatura_recibo,
            comprovativo_pagamento=model.comprovativo_pagamento,
            observacoes=model.observacoes,
            tipo_movimento=model.tipo_movimento,
            estado_pagamento=model.estado_pagamento,
            fundo_tipo=getattr(model, "fundo_tipo", "BCS") or "BCS",
            estado_movimento=getattr(model, "estado_movimento", "criado") or "criado",
            codigo=getattr(model, "codigo", None),
            created_by=model.created_by,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )


class MovimentoHistoricoRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def registar(self, movimento_id: UUID, company_id: UUID, user_id: UUID, changes: dict) -> None:
        for campo, (antes, depois) in changes.items():
            self.db.add(MovimentoHistoricoModel(
                id=uuid4(),
                movimento_id=movimento_id,
                company_id=company_id,
                user_id=user_id,
                campo=campo,
                valor_anterior=str(antes) if antes is not None else None,
                valor_novo=str(depois) if depois is not None else None,
            ))
        await self.db.flush()

    async def listar(self, movimento_id: UUID) -> list:
        result = await self.db.execute(
            select(MovimentoHistoricoModel, UserModel.full_name)
            .join(UserModel, MovimentoHistoricoModel.user_id == UserModel.id)
            .where(MovimentoHistoricoModel.movimento_id == movimento_id)
            .order_by(MovimentoHistoricoModel.created_at.desc())
        )
        return [
            {
                "id": str(row.MovimentoHistoricoModel.id),
                "movimento_id": str(row.MovimentoHistoricoModel.movimento_id),
                "campo": row.MovimentoHistoricoModel.campo,
                "valor_anterior": row.MovimentoHistoricoModel.valor_anterior,
                "valor_novo": row.MovimentoHistoricoModel.valor_novo,
                "user_name": row.full_name,
                "created_at": row.MovimentoHistoricoModel.created_at.isoformat(),
            }
            for row in result.all()
        ]


class AuditLogRepository(IAuditLogRepository):
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, entity: AuditLog) -> AuditLog:
        model = AuditLogModel(
            id=entity.id or uuid4(),
            user_id=entity.user_id,
            company_id=entity.company_id,
            acao=entity.acao,
            entidade=entity.entidade,
            entidade_id=entity.entidade_id,
            dados_anteriores=entity.dados_anteriores,
            dados_novos=entity.dados_novos,
            ip_address=entity.ip_address,
            user_agent=entity.user_agent,
        )
        self.db.add(model)
        await self.db.flush()
        return entity

    async def get_all(self, company_id: UUID, skip: int = 0, limit: int = 50) -> List[AuditLog]:
        result = await self.db.execute(
            select(AuditLogModel)
            .where(AuditLogModel.company_id == company_id)
            .order_by(AuditLogModel.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_by_id(self, id: UUID) -> Optional[AuditLog]:
        result = await self.db.execute(select(AuditLogModel).where(AuditLogModel.id == id))
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_all_base(self, skip: int = 0, limit: int = 100) -> List[AuditLog]:
        return await self.get_all(UUID(int=0), skip, limit)

    async def update(self, id: UUID, entity: AuditLog) -> Optional[AuditLog]:
        return None

    async def delete(self, id: UUID) -> bool:
        return False

    @staticmethod
    def _to_entity(model: AuditLogModel) -> AuditLog:
        return AuditLog(
            id=model.id,
            user_id=model.user_id,
            company_id=model.company_id,
            acao=model.acao,
            entidade=model.entidade,
            entidade_id=model.entidade_id,
            dados_anteriores=model.dados_anteriores,
            dados_novos=model.dados_novos,
            ip_address=model.ip_address,
            user_agent=model.user_agent,
            created_at=model.created_at,
        )


__all__ = [
    "UserRepository",
    "FornecedorRepository",
    "ConceptoRepository",
    "FundoRepository",
    "MovimentoRepository",
    "MovimentoHistoricoRepository",
    "AuditLogRepository",
]
