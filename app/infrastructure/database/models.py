from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, Numeric, JSON, types
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
from uuid import uuid4


class UUIDType(types.TypeDecorator):
    """UUID portável: PostgreSQL e SQLite"""
    impl = types.String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        import uuid
        return uuid.UUID(str(value))


Base = declarative_base()
UUID = UUIDType


class UserModel(Base):
    __tablename__ = "users"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    grupo_id = Column(String(36), nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    is_superadmin = Column(Boolean, default=False, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    last_activity_at = Column(DateTime, nullable=True)
    suspended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    audit_logs = relationship("AuditLogModel", back_populates="user")
    movimentos = relationship("MovimentoFinanceiroModel", back_populates="created_by_user", foreign_keys="MovimentoFinanceiroModel.created_by")


class FornecedorModel(Base):
    __tablename__ = "fornecedores"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(255), nullable=False)
    nif = Column(String(20), nullable=False)
    telefone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    endereco = Column(Text, nullable=True)
    estado = Column(String(50), default="ativo", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    movimentos = relationship("MovimentoFinanceiroModel", back_populates="fornecedor")
    # Ponte para Cliente (Fase 4) — opcional, mesmo parceiro nas duas vertentes
    cliente_id = Column(String(36), nullable=True)


class ModuloModel(Base):
    """Módulo top-level do sistema (CRUD admin)."""
    __tablename__ = "modulos"
    id = Column(UUID(), primary_key=True, default=uuid4)
    nome = Column(String(80), nullable=False, unique=True, index=True)
    descricao = Column(String(255), nullable=True)
    icone = Column(String(50), nullable=True)
    ordem = Column(types.Integer, default=0, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaginaModel(Base):
    """Página (sub-menu) dentro de um Módulo. CRUD admin."""
    __tablename__ = "paginas"
    id = Column(UUID(), primary_key=True, default=uuid4)
    modulo_id = Column(String(36), nullable=True, index=True)  # FK varchar (consistente com legacy)
    nome = Column(String(80), nullable=False, index=True)
    descricao = Column(String(255), nullable=True)
    href = Column(String(150), nullable=True)
    icone = Column(String(50), nullable=True)
    ordem = Column(types.Integer, default=0, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PermissaoModel(Base):
    """Catálogo de permissões do sistema."""
    __tablename__ = "permissoes"
    id = Column(UUID(), primary_key=True, default=uuid4)
    codigo = Column(String(80), nullable=False, unique=True, index=True)  # ex: movimentos.criar
    modulo = Column(String(50), nullable=True, index=True)                 # nome do módulo (legacy + denormalizado)
    menu = Column(String(50), nullable=False, index=True)                  # nome da página (legacy + denormalizado)
    acao = Column(String(50), nullable=False)                              # listar, criar, editar, eliminar, ...
    descricao = Column(String(255), nullable=True)
    pagina_id = Column(String(36), nullable=True, index=True)              # FK varchar opcional para paginas


class OrigemFundoModel(Base):
    """Catálogo de origens possíveis para carregamentos de fundo (CRUD admin)."""
    __tablename__ = "origens_fundo"
    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(String(36), nullable=False, index=True)
    nome = Column(String(80), nullable=False)
    descricao = Column(String(255), nullable=True)
    ordem = Column(types.Integer, default=0, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)
    estado = Column(String(20), default="ativo", nullable=False)  # ativo / inativo
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GrupoModel(Base):
    """Grupos de utilizadores (por empresa)."""
    __tablename__ = "grupos"
    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(60), nullable=False)
    descricao = Column(String(255), nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)  # grupos default não-elimináveis
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GrupoPermissaoModel(Base):
    """Permissões de cada grupo (many-to-many)."""
    __tablename__ = "grupo_permissoes"
    grupo_id = Column(UUID(), ForeignKey("grupos.id"), primary_key=True)
    permissao_id = Column(UUID(), ForeignKey("permissoes.id"), primary_key=True)


class ClienteModel(Base):
    """Cliente: comprador, associado a Entradas (receita)."""
    __tablename__ = "clientes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(255), nullable=False)
    nif = Column(String(20), nullable=False)
    telefone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    endereco = Column(Text, nullable=True)
    estado = Column(String(50), default="ativo", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)
    # Ponte para Fornecedor (Fase 4)
    fornecedor_id = Column(String(36), nullable=True)


class ContaClienteModel(Base):
    """Conta de acesso ao Portal do Cliente (FrontOffice).

    Deliberadamente separada de UserModel: nunca deve ser aceite pelas
    dependencies de RBAC interno (get_current_user), e vice-versa —
    tokens JWT usam "type" distinto (cliente_access/cliente_refresh).
    """
    __tablename__ = "contas_cliente"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    cliente_id = Column(String(36), nullable=False, index=True)  # liga a ClienteModel
    email = Column(String(255), unique=True, nullable=False, index=True)
    telefone = Column(String(20), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    email_verificado = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConceptoModel(Base):
    __tablename__ = "conceitos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(255), nullable=False)
    descricao = Column(Text, nullable=True)
    estado = Column(String(50), default="ativo", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)

    movimentos = relationship("MovimentoFinanceiroModel", back_populates="conceito")


class ProdutoCategoriaModel(Base):
    """Categoria de produto (CRUD por empresa)."""
    __tablename__ = "produto_categorias"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(120), nullable=False)
    ordem = Column(types.Integer, default=0, nullable=False)
    estado = Column(String(20), default="ativo", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class ProdutoModel(Base):
    """Produto/Artigo."""
    __tablename__ = "produtos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    sku = Column(String(50), nullable=False, index=True)
    nome = Column(String(255), nullable=False)
    marca = Column(String(100), nullable=True)
    categoria_id = Column(String(36), nullable=True, index=True)
    unidade_medida = Column(String(10), default="un", nullable=False)  # L | kg | m3 | un | cx
    preco_base = Column(Numeric(15, 2), default=0, nullable=False)
    iva_pct = Column(Numeric(5, 2), default=14, nullable=False)
    descricao = Column(Text, nullable=True)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class ArmazemModel(Base):
    """Armazém / Localização física onde o stock reside. Multi-armazém
    desde o início (decisão D3 — docs/05)."""
    __tablename__ = "armazens"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    codigo = Column(String(20), nullable=False, index=True)
    nome = Column(String(120), nullable=False)
    morada = Column(Text, nullable=True)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class StockSaldoModel(Base):
    """Saldo de um produto num armazém.

    Disponível = ``qtd_actual − qtd_reservada`` (não persistido).
    Toda alteração de saldo passa por um StockMovimentoModel.
    """
    __tablename__ = "stock_saldos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    produto_id = Column(UUID(), nullable=False, index=True)
    armazem_id = Column(UUID(), nullable=False, index=True)
    qtd_actual = Column(Numeric(15, 3), default=0, nullable=False)
    qtd_reservada = Column(Numeric(15, 3), default=0, nullable=False)
    stock_minimo = Column(Numeric(15, 3), default=0, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StockMovimentoModel(Base):
    """Movimento imutável de stock.

    Tipos: ``entrada_compra | entrada_producao | entrada_ajuste |
    saida_venda | saida_perda | saida_ajuste | transferencia``.

    Para transferência, ``armazem_origem_id`` e ``armazem_destino_id``
    são ambos preenchidos e diferentes.
    """
    __tablename__ = "stock_movimentos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    produto_id = Column(UUID(), nullable=False, index=True)
    armazem_origem_id = Column(UUID(), nullable=True, index=True)
    armazem_destino_id = Column(UUID(), nullable=True, index=True)
    tipo = Column(String(30), nullable=False, index=True)
    quantidade = Column(Numeric(15, 3), nullable=False)
    custo_unitario = Column(Numeric(15, 2), nullable=True)
    documento_ref_tipo = Column(String(30), nullable=True)  # ex.: 'venda', 'compra'
    documento_ref_id = Column(String(36), nullable=True, index=True)
    motivo = Column(Text, nullable=True)
    estornado_de = Column(UUID(), nullable=True, index=True)  # ref ao movimento original
    created_by = Column(UUID(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class LocalizacaoModel(Base):
    """Localização física dentro de um armazém (corredor/prateleira)."""
    __tablename__ = "localizacoes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    armazem_id = Column(UUID(), nullable=False, index=True)
    codigo = Column(String(30), nullable=False)
    corredor = Column(String(30), nullable=True)
    prateleira = Column(String(30), nullable=True)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class InventarioModel(Base):
    """Contagem física de stock (inventário) por armazém."""
    __tablename__ = "inventarios"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    armazem_id = Column(UUID(), nullable=False, index=True)
    data_inicio = Column(DateTime, nullable=True)
    data_fim = Column(DateTime, nullable=True)
    estado = Column(String(20), default="rascunho", nullable=False, index=True)  # rascunho | em_curso | concluido
    responsavel_id = Column(UUID(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventarioLinhaModel(Base):
    """Linha de contagem: snapshot do sistema vs. contado."""
    __tablename__ = "inventario_linhas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    inventario_id = Column(UUID(), nullable=False, index=True)
    produto_id = Column(UUID(), nullable=False, index=True)
    localizacao_id = Column(UUID(), nullable=True, index=True)
    quantidade_sistema = Column(Numeric(15, 3), default=0, nullable=False)
    quantidade_contada = Column(Numeric(15, 3), nullable=True)
    contado_em = Column(DateTime, nullable=True)
    contado_por = Column(UUID(), nullable=True)


class DepartamentoModel(Base):
    """Departamento (domínio Capital Humano)."""
    __tablename__ = "departamentos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(120), nullable=False)
    responsavel_id = Column(UUID(), nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)


class ColaboradorModel(Base):
    __tablename__ = "colaboradores"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    user_id = Column(UUID(), nullable=True, index=True)
    nome = Column(String(150), nullable=False)
    cargo = Column(String(120), nullable=True)
    departamento_id = Column(UUID(), nullable=True, index=True)
    data_admissao = Column(DateTime, nullable=False)
    data_desligamento = Column(DateTime, nullable=True)
    salario_base = Column(Numeric(15, 2), default=0, nullable=False)
    estado = Column(String(20), default="ativo", nullable=False, index=True)  # ativo|ferias|licenca|desligado
    superior_id = Column(UUID(), nullable=True, index=True)
    telefone = Column(String(30), nullable=True)
    email_pessoal = Column(String(255), nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)


class ContratoRHModel(Base):
    __tablename__ = "contratos_rh"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)  # efetivo|termo|estagio|prestacao_servico
    data_inicio = Column(DateTime, nullable=False)
    data_fim = Column(DateTime, nullable=True)
    arquivo_url = Column(String(500), nullable=True)


class HorarioColaboradorModel(Base):
    __tablename__ = "horarios_colaborador"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    dia_semana = Column(Numeric(1, 0), nullable=False)
    hora_entrada = Column(String(5), nullable=False)
    hora_saida = Column(String(5), nullable=False)


class RegistoPontoModel(Base):
    __tablename__ = "registos_ponto"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    data_hora = Column(DateTime, default=datetime.utcnow)
    tipo = Column(String(10), nullable=False)  # entrada|saida
    origem = Column(String(15), default="manual", nullable=False)


class FaltaModel(Base):
    __tablename__ = "faltas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    data = Column(DateTime, nullable=False)
    tipo = Column(String(15), nullable=False)  # justificada|injustificada
    motivo = Column(Text, nullable=True)
    documento_url = Column(String(500), nullable=True)


class FeriasModel(Base):
    __tablename__ = "ferias"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    data_inicio = Column(DateTime, nullable=False)
    data_fim = Column(DateTime, nullable=False)
    dias = Column(Numeric(4, 0), nullable=False)
    estado = Column(String(20), default="solicitada", nullable=False, index=True)
    # solicitada|aprovada|rejeitada|em_curso|concluida
    aprovador_id = Column(UUID(), nullable=True)
    motivo_rejeicao = Column(Text, nullable=True)


class HoraExtraModel(Base):
    __tablename__ = "horas_extra"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    data = Column(DateTime, nullable=False)
    horas = Column(Numeric(5, 2), nullable=False)
    tipo = Column(String(15), default="normal", nullable=False)  # normal|feriado|noturna
    aprovado = Column(Boolean, default=False, nullable=False)
    aprovador_id = Column(UUID(), nullable=True)


class SubsidioModel(Base):
    __tablename__ = "subsidios"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)  # alimentacao|transporte|outro
    valor = Column(Numeric(12, 2), nullable=False)
    recorrente = Column(Boolean, default=True, nullable=False)


class DescontoModel(Base):
    __tablename__ = "descontos_rh"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)  # falta_injustificada|adiantamento|outro
    valor = Column(Numeric(12, 2), nullable=False)
    referente_periodo = Column(String(10), nullable=False)  # "YYYY-MM"


class FolhaPagamentoModel(Base):
    __tablename__ = "folhas_pagamento"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    periodo = Column(String(10), nullable=False)  # "YYYY-MM"
    estado = Column(String(15), default="aberta", nullable=False, index=True)  # aberta|processada|paga
    data_processamento = Column(DateTime, nullable=True)


class ReciboSalarioModel(Base):
    __tablename__ = "recibos_salario"

    id = Column(UUID(), primary_key=True, default=uuid4)
    folha_pagamento_id = Column(UUID(), nullable=False, index=True)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    salario_base = Column(Numeric(15, 2), nullable=False)
    total_subsidios = Column(Numeric(15, 2), default=0, nullable=False)
    total_descontos = Column(Numeric(15, 2), default=0, nullable=False)
    total_horas_extra = Column(Numeric(15, 2), default=0, nullable=False)
    valor_liquido = Column(Numeric(15, 2), nullable=False)
    pdf_url = Column(String(500), nullable=True)


class ObjetivoModel(Base):
    __tablename__ = "objetivos_rh"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    periodo = Column(String(10), nullable=False)
    descricao = Column(Text, nullable=False)
    meta = Column(String(255), nullable=True)
    progresso_pct = Column(Numeric(5, 2), default=0, nullable=False)
    estado = Column(String(20), default="em_curso", nullable=False)  # em_curso|atingido|nao_atingido


class CompetenciaModel(Base):
    __tablename__ = "competencias"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(120), nullable=False)
    descricao = Column(Text, nullable=True)


class AvaliacaoRHModel(Base):
    __tablename__ = "avaliacoes_rh"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    periodo = Column(String(10), nullable=False)
    avaliador_id = Column(UUID(), nullable=True)
    nota_geral = Column(Numeric(3, 1), nullable=False)
    pontos_fortes = Column(Text, nullable=True)
    pontos_melhorar = Column(Text, nullable=True)
    data = Column(DateTime, default=datetime.utcnow)


class FormacaoModel(Base):
    __tablename__ = "formacoes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    colaborador_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(150), nullable=False)
    instituicao = Column(String(150), nullable=True)
    data_inicio = Column(DateTime, nullable=True)
    data_fim = Column(DateTime, nullable=True)
    certificado_url = Column(String(500), nullable=True)


class TransferenciaFundoModel(Base):
    """Transferência entre fundos (domínio Gestão Financeira / Tesouraria)."""
    __tablename__ = "transferencias_fundo"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    fundo_origem_tipo = Column(String(10), nullable=False)
    fundo_destino_tipo = Column(String(10), nullable=False)
    valor = Column(Numeric(15, 2), nullable=False)
    data = Column(DateTime, default=datetime.utcnow)
    motivo = Column(Text, nullable=True)
    movimento_origem_id = Column(UUID(), nullable=True)
    movimento_destino_id = Column(UUID(), nullable=True)
    created_by = Column(UUID(), nullable=True)


class CentroCustoModel(Base):
    __tablename__ = "centros_custo"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    codigo = Column(String(20), nullable=False)
    nome = Column(String(120), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)


class AprovacaoFinanceiraModel(Base):
    __tablename__ = "aprovacoes_financeiras"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    movimento_id = Column(UUID(), nullable=False, index=True)
    valor = Column(Numeric(15, 2), nullable=False)
    solicitante_id = Column(UUID(), nullable=False)
    aprovador_id = Column(UUID(), nullable=True)
    estado = Column(String(20), default="pendente", nullable=False, index=True)  # pendente|aprovado|rejeitado
    motivo_rejeicao = Column(Text, nullable=True)
    data_decisao = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ContaReceberModel(Base):
    __tablename__ = "contas_receber"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    cliente_id = Column(String(36), nullable=False, index=True)
    origem_tipo = Column(String(20), nullable=False)  # venda | manual
    origem_id = Column(String(36), nullable=True)
    valor = Column(Numeric(15, 2), nullable=False)
    data_vencimento = Column(DateTime, nullable=False)
    data_recebimento = Column(DateTime, nullable=True)
    estado = Column(String(20), default="pendente", nullable=False, index=True)
    # pendente | parcial | pago | atrasado | cancelado
    movimento_id = Column(UUID(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ContaPagarModel(Base):
    __tablename__ = "contas_pagar"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    fornecedor_id = Column(UUID(), nullable=False, index=True)
    origem_tipo = Column(String(20), nullable=False)  # pedido_compra | manual
    origem_id = Column(String(36), nullable=True)
    valor = Column(Numeric(15, 2), nullable=False)
    data_vencimento = Column(DateTime, nullable=False)
    data_pagamento = Column(DateTime, nullable=True)
    estado = Column(String(20), default="pendente", nullable=False, index=True)
    movimento_id = Column(UUID(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PlanoContasModel(Base):
    __tablename__ = "plano_contas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    codigo = Column(String(20), nullable=False)
    nome = Column(String(150), nullable=False)
    classe = Column(Numeric(1, 0), nullable=False)  # 1-7
    tipo = Column(String(15), nullable=False)  # analitica | sintetica
    conta_pai_id = Column(UUID(), nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)


class TaxaImpostoModel(Base):
    __tablename__ = "taxas_imposto"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(60), nullable=False)
    percentagem = Column(Numeric(6, 3), nullable=False)
    tipo = Column(String(15), default="iva", nullable=False)  # iva | retencao | outro
    padrao = Column(Boolean, default=False, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)


class ObrigacaoFiscalModel(Base):
    __tablename__ = "obrigacoes_fiscais"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(150), nullable=False)
    prazo = Column(DateTime, nullable=False)
    recorrencia = Column(String(20), nullable=True)  # mensal | trimestral | anual | unica
    estado = Column(String(20), default="pendente", nullable=False, index=True)  # pendente | cumprida


class LeadModel(Base):
    """Lead comercial (domínio Gestão Comercial / CRM)."""
    __tablename__ = "leads"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(150), nullable=False)
    empresa = Column(String(150), nullable=True)
    telefone = Column(String(30), nullable=True)
    email = Column(String(255), nullable=True)
    origem = Column(String(30), default="outro", nullable=False)  # indicacao|site|feira|redes_sociais|outro
    estado = Column(String(20), default="novo", nullable=False, index=True)  # novo|qualificado|descartado|convertido
    responsavel_id = Column(UUID(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class EtapaPipelineModel(Base):
    __tablename__ = "etapas_pipeline"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(60), nullable=False)
    ordem = Column(Numeric(4, 0), default=0, nullable=False)
    cor = Column(String(20), nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)


class OportunidadeModel(Base):
    __tablename__ = "oportunidades"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    lead_id = Column(UUID(), nullable=True, index=True)
    cliente_id = Column(String(36), nullable=True, index=True)
    titulo = Column(String(150), nullable=False)
    valor_estimado = Column(Numeric(15, 2), default=0, nullable=False)
    probabilidade_pct = Column(Numeric(5, 2), default=50, nullable=False)
    etapa_pipeline_id = Column(UUID(), nullable=False, index=True)
    responsavel_id = Column(UUID(), nullable=True)
    data_fecho_prevista = Column(DateTime, nullable=True)
    estado = Column(String(20), default="aberta", nullable=False, index=True)  # aberta|ganha|perdida
    motivo_perda = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ViaturaModel(Base):
    __tablename__ = "viaturas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    cliente_id = Column(String(36), nullable=True, index=True)  # nullable: walk-in sem cliente cadastrado
    matricula = Column(String(20), nullable=False)
    marca = Column(String(60), nullable=True)
    modelo = Column(String(60), nullable=True)
    cor = Column(String(30), nullable=True)
    vin = Column(String(30), nullable=True)
    categoria_veiculo_id = Column(UUID(), nullable=True, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)


class ProgramaFidelizacaoModel(Base):
    __tablename__ = "programas_fidelizacao"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(120), nullable=False)
    pontos_por_1000kz = Column(Numeric(6, 2), default=1, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)


class SaldoFidelizacaoModel(Base):
    __tablename__ = "saldos_fidelizacao"

    id = Column(UUID(), primary_key=True, default=uuid4)
    cliente_id = Column(String(36), nullable=False, index=True)
    programa_id = Column(UUID(), nullable=False, index=True)
    pontos_acumulados = Column(Numeric(12, 2), default=0, nullable=False)
    cashback_saldo = Column(Numeric(12, 2), default=0, nullable=False)


class VisitaModel(Base):
    __tablename__ = "visitas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    oportunidade_id = Column(UUID(), nullable=True, index=True)
    cliente_id = Column(String(36), nullable=True, index=True)
    data_hora = Column(DateTime, nullable=False)
    tipo = Column(String(20), default="presencial", nullable=False)  # presencial | remota
    responsavel_id = Column(UUID(), nullable=True)
    notas = Column(Text, nullable=True)
    estado = Column(String(20), default="agendada", nullable=False, index=True)  # agendada|realizada|cancelada


class TarefaModel(Base):
    __tablename__ = "tarefas_crm"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    titulo = Column(String(150), nullable=False)
    descricao = Column(Text, nullable=True)
    tipo = Column(String(20), default="followup", nullable=False)  # chamada|email|reuniao|followup
    responsavel_id = Column(UUID(), nullable=True)
    relacionado_tipo = Column(String(20), nullable=True)  # lead|oportunidade|cliente
    relacionado_id = Column(String(36), nullable=True)
    prazo = Column(DateTime, nullable=True)
    estado = Column(String(20), default="pendente", nullable=False, index=True)  # pendente|concluida
    prioridade = Column(String(10), default="media", nullable=False)  # baixa|media|alta
    created_at = Column(DateTime, default=datetime.utcnow)


class SegmentoClienteModel(Base):
    __tablename__ = "segmentos_cliente"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(120), nullable=False)
    criterios = Column(Text, nullable=True)  # JSON: filtros sobre Cliente
    deleted_at = Column(DateTime, nullable=True, index=True)


class CampanhaModel(Base):
    __tablename__ = "campanhas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(150), nullable=False)
    tipo = Column(String(20), nullable=False)  # sms|whatsapp|email|promocao
    segmento_id = Column(UUID(), nullable=True)
    conteudo = Column(Text, nullable=False)
    data_agendada = Column(DateTime, nullable=True)
    estado = Column(String(20), default="rascunho", nullable=False, index=True)  # rascunho|agendada|enviada|cancelada
    enviados_count = Column(Numeric(10, 0), default=0, nullable=False)
    entregues_count = Column(Numeric(10, 0), default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReclamacaoModel(Base):
    __tablename__ = "reclamacoes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    cliente_id = Column(String(36), nullable=True, index=True)
    assunto = Column(String(150), nullable=False)
    descricao = Column(Text, nullable=False)
    canal = Column(String(20), nullable=False)  # telefone|email|whatsapp|presencial|app
    gravidade = Column(String(10), default="media", nullable=False)  # baixa|media|alta
    estado = Column(String(20), default="aberta", nullable=False, index=True)  # aberta|em_analise|resolvida|fechada
    responsavel_id = Column(UUID(), nullable=True)
    data_abertura = Column(DateTime, default=datetime.utcnow)
    data_resolucao = Column(DateTime, nullable=True)


class SugestaoModel(Base):
    __tablename__ = "sugestoes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    cliente_id = Column(String(36), nullable=True, index=True)
    descricao = Column(Text, nullable=False)
    estado = Column(String(20), default="recebida", nullable=False, index=True)
    # recebida | em_avaliacao | aceite | rejeitada | implementada
    created_at = Column(DateTime, default=datetime.utcnow)


class TicketModel(Base):
    __tablename__ = "tickets_atendimento"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    cliente_id = Column(String(36), nullable=True, index=True)
    assunto = Column(String(150), nullable=False)
    descricao = Column(Text, nullable=False)
    prioridade = Column(String(10), default="media", nullable=False)  # baixa|media|alta|urgente
    estado = Column(String(20), default="aberto", nullable=False, index=True)  # aberto|em_curso|resolvido|fechado
    responsavel_id = Column(UUID(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AtendimentoRegistroModel(Base):
    __tablename__ = "atendimento_registros"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    cliente_id = Column(String(36), nullable=True, index=True)
    canal = Column(String(20), nullable=False)
    assunto = Column(String(150), nullable=True)
    descricao = Column(Text, nullable=True)
    responsavel_id = Column(UUID(), nullable=True)
    data_hora = Column(DateTime, default=datetime.utcnow)
    satisfacao = Column(Numeric(2, 0), nullable=True)


class MesaModel(Base):
    """Mesa (domínio Restauração — Base Comum)."""
    __tablename__ = "mesas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    area_servico_id = Column(UUID(), nullable=True, index=True)
    numero = Column(String(10), nullable=False)
    capacidade = Column(Numeric(4, 0), default=4, nullable=False)
    estado = Column(String(20), default="livre", nullable=False, index=True)  # livre | ocupada | reservada | limpeza
    deleted_at = Column(DateTime, nullable=True, index=True)


class ItemMenuModel(Base):
    __tablename__ = "itens_menu"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    tipo_negocio = Column(String(20), nullable=False, index=True)  # bar | restaurante | churrasqueira
    nome = Column(String(150), nullable=False)
    descricao = Column(Text, nullable=True)
    preco = Column(Numeric(10, 2), nullable=False)
    categoria = Column(String(60), nullable=True)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    ingredientes = Column(Text, nullable=True)  # JSON: [{produto_id, quantidade}]
    deleted_at = Column(DateTime, nullable=True, index=True)


class ComandaModel(Base):
    __tablename__ = "comandas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    mesa_id = Column(UUID(), nullable=True, index=True)
    cliente_id = Column(String(36), nullable=True)
    aberta_em = Column(DateTime, default=datetime.utcnow)
    fechada_em = Column(DateTime, nullable=True)
    estado = Column(String(20), default="aberta", nullable=False, index=True)  # aberta | fechada | paga | cancelada
    garcom_id = Column(UUID(), nullable=True)
    venda_id = Column(UUID(), nullable=True)


class ComandaLinhaModel(Base):
    __tablename__ = "comanda_linhas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    comanda_id = Column(UUID(), nullable=False, index=True)
    item_id = Column(UUID(), nullable=False, index=True)
    nome_snapshot = Column(String(150), nullable=False)
    preco_snapshot = Column(Numeric(10, 2), nullable=False)
    quantidade = Column(Numeric(8, 2), default=1, nullable=False)
    observacoes = Column(Text, nullable=True)
    estado = Column(String(20), default="pedido", nullable=False, index=True)
    # pedido | em_preparacao | pronto | entregue | cancelado


class ReservaMesaModel(Base):
    __tablename__ = "reservas_mesa"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    mesa_id = Column(UUID(), nullable=True)
    cliente_id = Column(String(36), nullable=True)
    nome_cliente = Column(String(150), nullable=True)
    data_hora = Column(DateTime, nullable=False)
    numero_pessoas = Column(Numeric(4, 0), default=2, nullable=False)
    estado = Column(String(20), default="confirmada", nullable=False, index=True)  # confirmada | cancelada | concluida | no_show


class HappyHourModel(Base):
    __tablename__ = "happy_hour"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    dia_semana = Column(Numeric(1, 0), nullable=False)  # 0=domingo .. 6=sábado
    hora_inicio = Column(String(5), nullable=False)
    hora_fim = Column(String(5), nullable=False)
    desconto_pct = Column(Numeric(5, 2), nullable=False)
    itens_aplicaveis = Column(Text, nullable=True)  # JSON: array de item_id, vazio = todos
    deleted_at = Column(DateTime, nullable=True, index=True)


class ComboModel(Base):
    __tablename__ = "combos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(150), nullable=False)
    itens = Column(Text, nullable=False)  # JSON: [{item_menu_id, quantidade}]
    preco_combo = Column(Numeric(10, 2), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)


class PedidoProducaoModel(Base):
    __tablename__ = "pedidos_producao"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    comanda_linha_id = Column(UUID(), nullable=True, index=True)
    estado = Column(String(20), default="fila", nullable=False, index=True)  # fila | em_preparacao | pronto
    estacao_producao = Column(String(60), nullable=True)
    tempo_estimado_minutos = Column(Numeric(5, 0), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)


class FilialModel(Base):
    """Unidade física (filial/estação) da empresa — permite comparativo
    de indicadores entre unidades (ver PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md,
    Fase 5)."""
    __tablename__ = "filiais"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(120), nullable=False)
    morada = Column(Text, nullable=True)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class AreaServicoModel(Base):
    """Área de serviço dentro de uma filial (domínio Operações)."""
    __tablename__ = "areas_servico"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    filial_id = Column(UUID(), nullable=True, index=True)
    nome = Column(String(120), nullable=False)
    tipo = Column(String(30), nullable=False)  # bomba | lavagem | loja | restauracao
    activo = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class EquipamentoModel(Base):
    __tablename__ = "equipamentos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    area_servico_id = Column(UUID(), nullable=True, index=True)
    nome = Column(String(120), nullable=False)
    tipo = Column(String(30), nullable=False)  # maquina_lavagem | outro
    estado = Column(String(20), default="operacional", nullable=False, index=True)
    ultima_manutencao = Column(DateTime, nullable=True)
    proxima_manutencao_prevista = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class TurnoOperacionalModel(Base):
    """Turno de funcionamento da estação (não confundir com turno de RH)."""
    __tablename__ = "turnos_operacionais"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(60), nullable=False)
    hora_inicio = Column(String(5), nullable=False)  # "HH:MM"
    hora_fim = Column(String(5), nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)


class TipoLavagemModel(Base):
    __tablename__ = "tipos_lavagem"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    codigo = Column(String(30), nullable=False)
    nome = Column(String(120), nullable=False)
    descricao = Column(Text, nullable=True)
    preco_base = Column(Numeric(10, 2), nullable=False)
    duracao_estimada_minutos = Column(Numeric(6, 0), default=30, nullable=False)
    agua_estimada_litros = Column(Numeric(8, 2), default=0, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)


class BoxLavagemModel(Base):
    __tablename__ = "boxes_lavagem"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    area_servico_id = Column(UUID(), nullable=True)
    filial_id = Column(UUID(), nullable=True, index=True)  # denormalizado p/ agregações por filial (Fase 5)
    codigo = Column(String(20), nullable=False)
    nome = Column(String(120), nullable=False)
    estado = Column(String(20), default="disponivel", nullable=False, index=True)  # disponivel | ocupado | manutencao
    capacidade = Column(Numeric(4, 0), default=1, nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)


class SlotLavagemModel(Base):
    __tablename__ = "slots_lavagem"

    id = Column(UUID(), primary_key=True, default=uuid4)
    box_id = Column(UUID(), nullable=False, index=True)
    data_hora_inicio = Column(DateTime, nullable=False)
    data_hora_fim = Column(DateTime, nullable=False)
    estado = Column(String(20), default="disponivel", nullable=False, index=True)  # disponivel | reservado | bloqueado
    preco_override = Column(Numeric(10, 2), nullable=True)


class OrdemLavagemModel(Base):
    __tablename__ = "ordens_lavagem"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    cliente_id = Column(String(36), nullable=True)
    viatura_id = Column(String(36), nullable=True)
    tipo_lavagem_id = Column(UUID(), nullable=False, index=True)
    box_id = Column(UUID(), nullable=True, index=True)
    slot_id = Column(UUID(), nullable=True)
    estado = Column(String(20), default="rascunho", nullable=False, index=True)
    # rascunho | agendada | confirmada | checkin | em_curso | controlo_qualidade | concluida | paga
    origem = Column(String(20), default="backoffice_walkin", nullable=False, index=True)
    # portal_cliente | backoffice_walkin | backoffice_telefone
    equipa = Column(Text, nullable=True)  # CSV de user_id, preenchido automaticamente via EscalaTurno
    colaborador_responsavel_id = Column(UUID(), nullable=True)  # opcional, p/ produtividade individual (Fase 4)
    agua_consumida_litros = Column(Numeric(8, 2), nullable=True)
    quimicos_consumidos = Column(Text, nullable=True)  # JSON serializado: [{produto_id, quantidade}]
    re_lavagem_de_id = Column(UUID(), nullable=True)
    venda_id = Column(UUID(), nullable=True)
    lembrete_enviado = Column(Boolean, default=False, nullable=False)
    # Timestamps por transição de estado — updated_at é sobrescrito a cada
    # transição, por isso não serve para medir tempo de atendimento (ver
    # PROMPT_DASHBOARD_OPERACIONAL_SPRINTS.md, Fase 2).
    checkin_em = Column(DateTime, nullable=True)
    iniciado_em = Column(DateTime, nullable=True)
    controlo_qualidade_em = Column(DateTime, nullable=True)
    concluido_em = Column(DateTime, nullable=True)
    preco_total_snapshot = Column(Numeric(10, 2), nullable=True)  # gravado na conclusão (Fase 3)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ControloQualidadeLavagemModel(Base):
    __tablename__ = "controlo_qualidade_lavagem"

    id = Column(UUID(), primary_key=True, default=uuid4)
    ordem_lavagem_id = Column(UUID(), nullable=False, index=True)
    avaliador_id = Column(UUID(), nullable=True)
    pontuacao = Column(Numeric(2, 0), nullable=False)
    observacoes = Column(Text, nullable=True)
    data = Column(DateTime, default=datetime.utcnow)


class CategoriaVeiculoModel(Base):
    """Categoria de veículo (mota, ligeiro, SUV/pickup, pesado) — define
    fatores multiplicadores de preço e consumo de água para a Lavagem.
    Configurável pelo backoffice, nunca hardcoded no código."""
    __tablename__ = "categorias_veiculo"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    codigo = Column(String(30), nullable=False)
    nome = Column(String(80), nullable=False)
    fator_preco = Column(Numeric(4, 2), default=1, nullable=False)
    fator_agua = Column(Numeric(4, 2), default=1, nullable=False)
    ordem = Column(Numeric(4, 0), default=0, nullable=False)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)


class ExtraLavagemModel(Base):
    """Serviço adicional opcional (encerar, polimento, higienização A/C)
    que pode ser somado a qualquer OrdemLavagem."""
    __tablename__ = "extras_lavagem"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    codigo = Column(String(30), nullable=False)
    nome = Column(String(120), nullable=False)
    preco = Column(Numeric(10, 2), nullable=False)
    duracao_adicional_minutos = Column(Numeric(5, 0), default=0, nullable=False)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)


class OrdemLavagemExtraModel(Base):
    __tablename__ = "ordem_lavagem_extras"

    id = Column(UUID(), primary_key=True, default=uuid4)
    ordem_lavagem_id = Column(UUID(), nullable=False, index=True)
    extra_id = Column(UUID(), nullable=False, index=True)
    preco_aplicado = Column(Numeric(10, 2), nullable=False)  # snapshot do preço no momento


class EquipaLavagemModel(Base):
    __tablename__ = "equipas_lavagem"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    nome = Column(String(120), nullable=False)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)


class EquipaMembroModel(Base):
    __tablename__ = "equipa_membros"

    id = Column(UUID(), primary_key=True, default=uuid4)
    equipa_id = Column(UUID(), nullable=False, index=True)
    user_id = Column(UUID(), nullable=False, index=True)


class EscalaTurnoModel(Base):
    """Escalação de uma equipa a um box, num turno, numa data. Usada para
    atribuir automaticamente a equipa a uma OrdemLavagem no início da
    lavagem (ver iniciar() em operacoes_lavagem.py)."""
    __tablename__ = "escalas_turno"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    equipa_id = Column(UUID(), nullable=False, index=True)
    box_id = Column(UUID(), nullable=False, index=True)
    turno_id = Column(UUID(), nullable=False, index=True)
    data = Column(DateTime, nullable=False, index=True)
    activo = Column(Boolean, default=True, nullable=False, index=True)


class TanqueAguaModel(Base):
    __tablename__ = "tanques_agua"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    codigo = Column(String(30), nullable=False)
    nome = Column(String(120), nullable=False)
    tipo = Column(String(20), nullable=False)  # limpa | reciclada | tratada | pluvial
    capacidade_litros = Column(Numeric(12, 2), nullable=False)
    nivel_atual_litros = Column(Numeric(12, 2), default=0, nullable=False)
    nivel_minimo_litros = Column(Numeric(12, 2), default=0, nullable=False)
    ph = Column(Numeric(4, 2), nullable=True)
    turbidez = Column(Numeric(6, 2), nullable=True)
    condutividade = Column(Numeric(8, 2), nullable=True)
    tem_sensor = Column(Boolean, default=False, nullable=False)
    sensor_id = Column(String(50), nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)


class ConsumoAguaModel(Base):
    __tablename__ = "consumos_agua"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    tanque_agua_id = Column(UUID(), nullable=False, index=True)
    litros_consumidos = Column(Numeric(10, 2), nullable=False)
    tipo = Column(String(20), nullable=False)  # lavagem | limpeza | outro
    referencia_id = Column(UUID(), nullable=True)
    referencia_tipo = Column(String(30), nullable=True)
    custo_por_litro = Column(Numeric(8, 4), nullable=True)
    custo_total = Column(Numeric(12, 2), nullable=True)
    data = Column(DateTime, default=datetime.utcnow)


class PromocaoModel(Base):
    """Promoção de produto/categoria (domínio Comércio / Loja)."""
    __tablename__ = "promocoes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    produto_id = Column(UUID(), nullable=True, index=True)
    categoria_id = Column(String(36), nullable=True, index=True)
    tipo = Column(String(20), nullable=False)  # percentual | valor_fixo
    valor = Column(Numeric(15, 2), nullable=False)
    data_inicio = Column(DateTime, nullable=False)
    data_fim = Column(DateTime, nullable=False)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class DevolucaoModel(Base):
    """Devolução de uma venda concluída (domínio Comércio / POS)."""
    __tablename__ = "devolucoes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    venda_id = Column(UUID(), nullable=False, index=True)
    valor_devolvido = Column(Numeric(15, 2), nullable=False)
    forma_devolucao = Column(String(20), nullable=False)  # numerario | credito_cliente | troca
    responsavel_id = Column(UUID(), nullable=True)
    data = Column(DateTime, default=datetime.utcnow)


class DevolucaoLinhaModel(Base):
    __tablename__ = "devolucao_linhas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    devolucao_id = Column(UUID(), nullable=False, index=True)
    produto_id = Column(UUID(), nullable=False, index=True)
    quantidade = Column(Numeric(15, 3), nullable=False)
    motivo = Column(String(20), nullable=False)  # normal | danificado


class LojaOnlineConfigModel(Base):
    """Configuração da loja online (domínio Comércio / E-Commerce)."""
    __tablename__ = "loja_online_config"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, unique=True, index=True)
    dominio = Column(String(255), nullable=True)
    tema = Column(String(50), default="default", nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    metodos_entrega = Column(String(255), default="delivery,click_collect", nullable=False)
    moeda = Column(String(10), default="AOA", nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CupaoModel(Base):
    __tablename__ = "cupoes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    codigo = Column(String(30), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)  # percentual | valor_fixo
    valor = Column(Numeric(15, 2), nullable=False)
    validade = Column(DateTime, nullable=False)
    uso_maximo = Column(Numeric(10, 0), default=1, nullable=False)
    uso_atual = Column(Numeric(10, 0), default=0, nullable=False)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class PedidoOnlineModel(Base):
    """Pedido do portal público de e-commerce."""
    __tablename__ = "pedidos_online"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    cliente_id = Column(String(36), nullable=True, index=True)
    numero = Column(String(30), nullable=False, index=True)
    subtotal = Column(Numeric(15, 2), default=0, nullable=False)
    desconto_cupao = Column(Numeric(15, 2), default=0, nullable=False)
    total = Column(Numeric(15, 2), default=0, nullable=False)
    metodo_entrega = Column(String(20), nullable=False)  # delivery | click_collect
    endereco_entrega = Column(Text, nullable=True)
    estado = Column(String(30), default="pendente_pagamento", nullable=False, index=True)
    # pendente_pagamento | pago | em_preparacao | pronto | em_entrega | concluido | cancelado
    cupao_id = Column(UUID(), nullable=True)
    correlation_id = Column(String(36), nullable=False, unique=True, index=True)
    venda_id = Column(UUID(), nullable=True, index=True)
    armazem_id = Column(UUID(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PedidoOnlineLinhaModel(Base):
    __tablename__ = "pedido_online_linhas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    pedido_id = Column(UUID(), nullable=False, index=True)
    produto_id = Column(UUID(), nullable=False, index=True)
    sku_snapshot = Column(String(50), nullable=False)
    nome_snapshot = Column(String(255), nullable=False)
    quantidade = Column(Numeric(15, 3), nullable=False)
    preco_unitario = Column(Numeric(15, 2), nullable=False)


class ContratoFornecedorModel(Base):
    __tablename__ = "contratos_fornecedor"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    fornecedor_id = Column(UUID(), nullable=False, index=True)
    tipo = Column(String(60), nullable=True)
    data_inicio = Column(DateTime, nullable=False)
    data_fim = Column(DateTime, nullable=True)
    condicoes_pagamento = Column(Text, nullable=True)
    arquivo_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class AvaliacaoFornecedorModel(Base):
    __tablename__ = "avaliacoes_fornecedor"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    fornecedor_id = Column(UUID(), nullable=False, index=True)
    periodo = Column(String(20), nullable=False)  # ex.: "2026-Q2"
    nota_prazo = Column(Numeric(3, 1), nullable=False)
    nota_qualidade = Column(Numeric(3, 1), nullable=False)
    nota_preco = Column(Numeric(3, 1), nullable=False)
    observacoes = Column(Text, nullable=True)
    avaliado_por = Column(UUID(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RequisicaoModel(Base):
    """Requisição de compra interna (domínio Supply Chain / Compras)."""
    __tablename__ = "requisicoes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    solicitante_id = Column(UUID(), nullable=False)
    departamento = Column(String(120), nullable=True)
    data = Column(DateTime, default=datetime.utcnow)
    justificativa = Column(Text, nullable=True)
    estado = Column(String(20), default="rascunho", nullable=False, index=True)
    # rascunho | submetida | aprovada | rejeitada | convertida_pedido
    motivo_rejeicao = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class RequisicaoLinhaModel(Base):
    __tablename__ = "requisicao_linhas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    requisicao_id = Column(UUID(), nullable=False, index=True)
    produto_id = Column(UUID(), nullable=True, index=True)
    descricao_livre = Column(String(255), nullable=True)
    quantidade = Column(Numeric(15, 3), nullable=False)


class PedidoCompraModel(Base):
    """Pedido de Compra (Ordem de Compra) a um Fornecedor."""
    __tablename__ = "pedidos_compra"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    requisicao_id = Column(UUID(), nullable=True, index=True)
    fornecedor_id = Column(UUID(), nullable=False, index=True)
    numero = Column(String(30), nullable=False, index=True)
    data = Column(DateTime, default=datetime.utcnow)
    estado = Column(String(30), default="enviado", nullable=False, index=True)
    # enviado | confirmado | parcialmente_recebido | recebido | cancelado
    total = Column(Numeric(15, 2), default=0, nullable=False)
    ref_externa = Column(String(50), nullable=True)
    created_by = Column(UUID(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class PedidoCompraLinhaModel(Base):
    __tablename__ = "pedido_compra_linhas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    pedido_id = Column(UUID(), nullable=False, index=True)
    produto_id = Column(UUID(), nullable=False, index=True)
    quantidade = Column(Numeric(15, 3), nullable=False)
    quantidade_recebida = Column(Numeric(15, 3), default=0, nullable=False)
    preco_unitario = Column(Numeric(15, 2), nullable=False)


class RecepcaoModel(Base):
    """Receção de mercadoria de um Pedido de Compra."""
    __tablename__ = "recepcoes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    pedido_id = Column(UUID(), nullable=False, index=True)
    armazem_id = Column(UUID(), nullable=False)
    data = Column(DateTime, default=datetime.utcnow)
    estado = Column(String(20), default="rascunho", nullable=False, index=True)  # rascunho | confirmada
    responsavel_id = Column(UUID(), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RecepcaoLinhaModel(Base):
    __tablename__ = "recepcao_linhas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    recepcao_id = Column(UUID(), nullable=False, index=True)
    pedido_linha_id = Column(UUID(), nullable=False, index=True)
    produto_id = Column(UUID(), nullable=False, index=True)
    quantidade_esperada = Column(Numeric(15, 3), nullable=False)
    quantidade_recebida = Column(Numeric(15, 3), nullable=False)


class FundoModel(Base):
    __tablename__ = "fundos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    tipo = Column(String(10), nullable=False, default="BCS")  # BCS ou BFA
    data = Column(DateTime, default=datetime.utcnow)
    descricao = Column(Text, nullable=True)
    valor_disponivel = Column(Numeric(15, 2), nullable=False, default=0)
    acumulado = Column(Numeric(15, 2), nullable=False, default=0)
    saldo_atual = Column(Numeric(15, 2), nullable=False, default=0)
    observacao = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MovimentoFinanceiroModel(Base):
    __tablename__ = "movimentos_financeiros"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    data = Column(DateTime, default=datetime.utcnow, index=True)
    fornecedor_id = Column(UUID(), ForeignKey("fornecedores.id"), nullable=True, index=True)
    cliente_id = Column(String(36), nullable=True, index=True)
    conceito_id = Column(UUID(), ForeignKey("conceitos.id"), nullable=False, index=True)
    fatura_proforma = Column(String(50), nullable=True)
    valor = Column(Numeric(15, 2), nullable=False)
    fatura_recibo = Column(String(50), nullable=True)
    comprovativo_pagamento = Column(String(500), nullable=True)
    observacoes = Column(Text, nullable=True)
    codigo = Column(String(20), nullable=True, unique=True, index=True)
    tipo_movimento = Column(String(20), nullable=False, index=True)
    estado_pagamento = Column(String(20), nullable=False, index=True, default="pendente")
    estado_movimento = Column(String(20), nullable=False, default="criado", index=True)
    fundo_tipo = Column(String(10), nullable=False, default="BCS", index=True)
    created_by = Column(UUID(), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(UUID(), ForeignKey("users.id"), nullable=True)

    fornecedor = relationship("FornecedorModel", back_populates="movimentos")
    conceito = relationship("ConceptoModel", back_populates="movimentos")
    created_by_user = relationship("UserModel", back_populates="movimentos", foreign_keys=[created_by])
    closed_by_user = relationship("UserModel", foreign_keys=[closed_by])


class SavedFilterModel(Base):
    """Filtros guardados por utilizador (Épico 4)."""
    __tablename__ = "saved_filters"

    id = Column(UUID(), primary_key=True, default=uuid4)
    user_id = Column(UUID(), ForeignKey("users.id"), nullable=False, index=True)
    company_id = Column(UUID(), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    route = Column(String(100), nullable=False)
    params = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class MovimentoComentarioModel(Base):
    """Comentários por movimento (Épico UX v2)."""
    __tablename__ = "movimento_comentarios"

    id = Column(UUID(), primary_key=True, default=uuid4)
    movimento_id = Column(UUID(), ForeignKey("movimentos_financeiros.id"), nullable=False, index=True)
    company_id = Column(UUID(), nullable=False, index=True)
    user_id = Column(UUID(), ForeignKey("users.id"), nullable=False)
    texto = Column(Text, nullable=False)
    edited_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class MovimentoAnexoModel(Base):
    """Múltiplos anexos por movimento (Épico UX v2)."""
    __tablename__ = "movimento_anexos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    movimento_id = Column(UUID(), ForeignKey("movimentos_financeiros.id"), nullable=False, index=True)
    company_id = Column(UUID(), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    file_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=True)
    size_bytes = Column(types.Integer, nullable=True)
    uploaded_by = Column(UUID(), ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow, index=True)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(String(36), nullable=True)
    delete_reason = Column(String(500), nullable=True)
    tipo_fatura = Column(String(20), nullable=True)  # 'proforma' | 'recibo'


class MovimentoPagamentoModel(Base):
    """Sub-pagamentos de um movimento (Épico 6 — pagamento parcial real)."""
    __tablename__ = "movimento_pagamentos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    movimento_id = Column(UUID(), ForeignKey("movimentos_financeiros.id"), nullable=False, index=True)
    company_id = Column(UUID(), nullable=False, index=True)
    valor = Column(Numeric(15, 2), nullable=False)
    data = Column(DateTime, nullable=False, default=datetime.utcnow)
    fundo_tipo = Column(String(10), nullable=False, default="BCS")
    observacao = Column(Text, nullable=True)
    created_by = Column(UUID(), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    deleted_at = Column(DateTime, nullable=True)


class OrcamentoModel(Base):
    """Orçamento mensal por conceito (Épico 9.3)."""
    __tablename__ = "orcamentos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    conceito_id = Column(UUID(), ForeignKey("conceitos.id"), nullable=False, index=True)
    ano = Column(String(4), nullable=False)
    mes = Column(String(2), nullable=False)
    valor_planeado = Column(Numeric(15, 2), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PeriodoFechadoModel(Base):
    """Períodos contabilísticos fechados (Épico 10)."""
    __tablename__ = "periodos_fechados"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    ano = Column(String(4), nullable=False)
    mes = Column(String(2), nullable=False)
    fechado_por = Column(UUID(), ForeignKey("users.id"), nullable=False)
    fechado_em = Column(DateTime, default=datetime.utcnow)
    motivo = Column(Text, nullable=True)


class PasswordResetModel(Base):
    """Tokens de recuperação de senha."""
    __tablename__ = "password_resets"

    id = Column(UUID(), primary_key=True, default=uuid4)
    user_id = Column(UUID(), ForeignKey("users.id"), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CompanySettingsModel(Base):
    """Configurações editáveis por empresa: logo, NIF, morada, IBANs, etc."""
    __tablename__ = "company_settings"

    company_id = Column(UUID(), primary_key=True)
    nome = Column(String(255), nullable=False, default="")
    nif = Column(String(20), nullable=True)
    morada = Column(Text, nullable=True)
    telefone = Column(String(30), nullable=True)
    email = Column(String(255), nullable=True)
    iban_bcs = Column(String(50), nullable=True)
    iban_bfa = Column(String(50), nullable=True)
    logo_path = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(UUID(), nullable=True)


class FundoCarregamentoModel(Base):
    __tablename__ = "fundo_carregamentos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    fundo_id = Column(UUID(), ForeignKey("fundos.id"), nullable=False)
    user_id = Column(UUID(), ForeignKey("users.id"), nullable=False)
    valor_anterior = Column(Numeric(15, 2), nullable=False, default=0)
    valor_novo = Column(Numeric(15, 2), nullable=False)
    origem = Column(String(50), nullable=True)  # 'aumento_capital' | 'emprestimo' | 'receita' | 'outro'
    observacao = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("UserModel", foreign_keys=[user_id])


class MovimentoHistoricoModel(Base):
    __tablename__ = "movimento_historico"

    id = Column(UUID(), primary_key=True, default=uuid4)
    movimento_id = Column(UUID(), ForeignKey("movimentos_financeiros.id"), nullable=False, index=True)
    company_id = Column(UUID(), nullable=False, index=True)
    user_id = Column(UUID(), ForeignKey("users.id"), nullable=False)
    campo = Column(String(100), nullable=False)
    valor_anterior = Column(Text, nullable=True)
    valor_novo = Column(Text, nullable=True)
    observacao = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("UserModel", foreign_keys=[user_id])


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(), primary_key=True, default=uuid4)
    user_id = Column(UUID(), ForeignKey("users.id"), nullable=False, index=True)
    company_id = Column(UUID(), nullable=False, index=True)
    acao = Column(String(50), nullable=False, index=True)
    entidade = Column(String(100), nullable=False)
    entidade_id = Column(UUID(), nullable=False, index=True)
    dados_anteriores = Column(JSON, nullable=True)
    dados_novos = Column(JSON, nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("UserModel", back_populates="audit_logs")


# ─── Caixa / Vendas (F4) ────────────────────────────────────────────


class CaixaSessaoModel(Base):
    """Sessão de caixa — abertura/fecho de turno de um operador num armazém."""
    __tablename__ = "caixa_sessoes"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    utilizador_id = Column(UUID(), nullable=False, index=True)
    armazem_id = Column(UUID(), nullable=False, index=True)
    abertura_em = Column(DateTime, default=datetime.utcnow, index=True)
    fundo_inicial = Column(Numeric(15, 2), default=0, nullable=False)
    fecho_em = Column(DateTime, nullable=True)
    fundo_apurado = Column(Numeric(15, 2), nullable=True)
    fundo_contado = Column(Numeric(15, 2), nullable=True)
    diferenca = Column(Numeric(15, 2), nullable=True)
    observacao = Column(Text, nullable=True)
    estado = Column(String(20), default="aberta", nullable=False, index=True)


class VendaModel(Base):
    """Venda comercial. `numero_proforma` é gerado sequencialmente na
    conclusão da venda; `numero_fatura_interna` é opcionalmente registado
    depois, quando a fatura correspondente é emitida (faturação própria
    da aplicação, sem depender de ERP externo).
    """
    __tablename__ = "vendas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    company_id = Column(UUID(), nullable=False, index=True)
    sessao_id = Column(UUID(), nullable=True, index=True)
    cliente_id = Column(String(36), nullable=True, index=True)
    armazem_id = Column(UUID(), nullable=False, index=True)
    numero_proforma = Column(String(30), nullable=True, unique=True, index=True)
    data = Column(DateTime, default=datetime.utcnow, index=True)
    total_bruto = Column(Numeric(15, 2), default=0, nullable=False)
    total_desconto = Column(Numeric(15, 2), default=0, nullable=False)
    total_iva = Column(Numeric(15, 2), default=0, nullable=False)
    total_liquido = Column(Numeric(15, 2), default=0, nullable=False)
    estado = Column(String(20), default="rascunho", nullable=False, index=True)
    # rascunho | concluida | anulada
    correlation_id = Column(String(64), nullable=False, unique=True, index=True)
    numero_fatura_interna = Column(String(50), nullable=True, index=True)
    faturada_em = Column(DateTime, nullable=True)
    faturada_por = Column(UUID(), nullable=True)
    observacao = Column(Text, nullable=True)
    created_by = Column(UUID(), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    linhas = relationship("VendaLinhaModel", back_populates="venda",
                          cascade="all, delete-orphan")
    pagamentos = relationship("VendaPagamentoModel", back_populates="venda",
                              cascade="all, delete-orphan")


class VendaLinhaModel(Base):
    """Linha de uma venda. Guarda *snapshot* do produto para proteger o
    histórico de alterações futuras no catálogo."""
    __tablename__ = "venda_linhas"

    id = Column(UUID(), primary_key=True, default=uuid4)
    venda_id = Column(UUID(), ForeignKey("vendas.id"), nullable=False, index=True)
    produto_id = Column(UUID(), nullable=False, index=True)
    sku_snapshot = Column(String(50), nullable=False)
    nome_snapshot = Column(String(255), nullable=False)
    quantidade = Column(Numeric(15, 3), nullable=False)
    preco_unitario = Column(Numeric(15, 2), nullable=False)
    iva_pct = Column(Numeric(5, 2), default=0, nullable=False)
    desconto_pct = Column(Numeric(5, 2), default=0, nullable=False)
    subtotal = Column(Numeric(15, 2), nullable=False)

    venda = relationship("VendaModel", back_populates="linhas")


class VendaPagamentoModel(Base):
    """Pagamento de uma venda. Uma venda pode ter N pagamentos (misto)."""
    __tablename__ = "venda_pagamentos"

    id = Column(UUID(), primary_key=True, default=uuid4)
    venda_id = Column(UUID(), ForeignKey("vendas.id"), nullable=False, index=True)
    forma = Column(String(20), nullable=False)  # numerario | tpa | transferencia | cheque
    valor = Column(Numeric(15, 2), nullable=False)
    ref_externa = Column(String(120), nullable=True)
    data = Column(DateTime, default=datetime.utcnow)

    venda = relationship("VendaModel", back_populates="pagamentos")


__all__ = [
    "Base",
    "UUID",
    "UserModel",
    "FornecedorModel",
    "ConceptoModel",
    "FundoModel",
    "FundoCarregamentoModel",
    "MovimentoFinanceiroModel",
    "MovimentoHistoricoModel",
    "AuditLogModel",
    "ProdutoCategoriaModel",
    "ProdutoModel",
    "ArmazemModel",
    "StockSaldoModel",
    "StockMovimentoModel",
    "CaixaSessaoModel",
    "VendaModel",
    "VendaLinhaModel",
    "VendaPagamentoModel",
]
