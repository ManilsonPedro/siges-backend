"""
Script de migração manual.
Uso:
    DB_URL="postgresql://user:pass@host/db" python migrate.py
Ou editar a variável DATABASE_URL abaixo.
"""
import os
import sys
import psycopg


def _resolve_url() -> str:
    raw = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL") or ""
    if not raw:
        return ""
    url = raw
    for prefix in ["postgresql+psycopg://", "postgres+psycopg://"]:
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


# Atalho mantido para compatibilidade com o script standalone
url = _resolve_url()

MIGRATIONS = [
    "ALTER TABLE fundos ADD COLUMN IF NOT EXISTS tipo VARCHAR(10) DEFAULT 'BCS'",
    "ALTER TABLE movimentos_financeiros ADD COLUMN IF NOT EXISTS fundo_tipo VARCHAR(10) DEFAULT 'BCS'",
    "ALTER TABLE movimentos_financeiros ADD COLUMN IF NOT EXISTS codigo VARCHAR(20)",
    "ALTER TABLE movimentos_financeiros ADD COLUMN IF NOT EXISTS estado_movimento VARCHAR(20) DEFAULT 'criado'",
    """
    CREATE TABLE IF NOT EXISTS movimento_historico (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        company_id UUID NOT NULL,
        movimento_id UUID NOT NULL REFERENCES movimentos_financeiros(id),
        user_id UUID NOT NULL REFERENCES users(id),
        campo VARCHAR(100) NOT NULL,
        valor_anterior TEXT,
        valor_novo TEXT,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundo_carregamentos (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        company_id UUID NOT NULL,
        fundo_id UUID NOT NULL REFERENCES fundos(id),
        user_id UUID NOT NULL REFERENCES users(id),
        valor_anterior NUMERIC(15,2) NOT NULL DEFAULT 0,
        valor_novo NUMERIC(15,2) NOT NULL,
        observacao TEXT,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
    )
    """,
    """
    UPDATE movimentos_financeiros
    SET estado_movimento = CASE
        WHEN estado_pagamento IN ('pago', 'pago_total') THEN 'fechado'
        WHEN estado_pagamento IN ('pendente', 'pago_parcial') THEN 'pendente'
        ELSE 'criado'
    END
    WHERE estado_movimento IS NULL OR estado_movimento = 'criado'
    """,
    "UPDATE fundos SET tipo = 'BCS' WHERE tipo IS NULL",
    "UPDATE movimentos_financeiros SET fundo_tipo = 'BCS' WHERE fundo_tipo IS NULL",
    """
    WITH keepers AS (
        SELECT DISTINCT ON (company_id, tipo) id, company_id, tipo
        FROM fundos
        ORDER BY company_id, tipo, updated_at DESC NULLS LAST, created_at DESC NULLS LAST
    )
    UPDATE fundo_carregamentos fc
    SET fundo_id = k.id
    FROM fundos f, keepers k
    WHERE fc.fundo_id = f.id
      AND f.company_id = k.company_id
      AND COALESCE(f.tipo, 'BCS') = k.tipo
      AND fc.fundo_id <> k.id
    """,
    """
    DELETE FROM fundos
    WHERE id NOT IN (
        SELECT DISTINCT ON (company_id, tipo) id
        FROM fundos
        ORDER BY company_id, tipo, updated_at DESC NULLS LAST, created_at DESC NULLS LAST
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_fundos_company_tipo ON fundos (company_id, tipo)",
    # Fix legacy mistake: ix_fundos_company_id was created UNIQUE, which blocks having BCS + BFA for same company
    "DROP INDEX IF EXISTS ix_fundos_company_id",
    "CREATE INDEX IF NOT EXISTS ix_fundos_company_id ON fundos (company_id)",
    # Épico 1 — Configurações de Empresa
    """
    CREATE TABLE IF NOT EXISTS company_settings (
        company_id UUID PRIMARY KEY,
        nome VARCHAR(255) NOT NULL DEFAULT '',
        nif VARCHAR(20),
        morada TEXT,
        telefone VARCHAR(30),
        email VARCHAR(255),
        iban_bcs VARCHAR(50),
        iban_bfa VARCHAR(50),
        logo_path VARCHAR(500),
        updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
        updated_by UUID
    )
    """,
    # Épico 4 — Filtros guardados
    """
    CREATE TABLE IF NOT EXISTS saved_filters (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        company_id UUID NOT NULL,
        name VARCHAR(100) NOT NULL,
        route VARCHAR(100) NOT NULL,
        params JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_saved_filters_user_id ON saved_filters (user_id)",
    # Épico 10 — Períodos fechados
    """
    CREATE TABLE IF NOT EXISTS periodos_fechados (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        company_id UUID NOT NULL,
        ano VARCHAR(4) NOT NULL,
        mes VARCHAR(2) NOT NULL,
        fechado_por UUID NOT NULL REFERENCES users(id),
        fechado_em TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
        motivo TEXT
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_periodos_company_ano_mes ON periodos_fechados (company_id, ano, mes)",
    # Épico 6 — Pagamento parcial
    """
    CREATE TABLE IF NOT EXISTS movimento_pagamentos (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        movimento_id UUID NOT NULL REFERENCES movimentos_financeiros(id),
        company_id UUID NOT NULL,
        valor NUMERIC(15,2) NOT NULL,
        data TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
        fundo_tipo VARCHAR(10) NOT NULL DEFAULT 'BCS',
        observacao TEXT,
        created_by UUID NOT NULL REFERENCES users(id),
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
        deleted_at TIMESTAMP WITHOUT TIME ZONE
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_pagamentos_movimento ON movimento_pagamentos (movimento_id)",
    # Épico 9.3 — Orçamentos
    """
    CREATE TABLE IF NOT EXISTS orcamentos (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        company_id UUID NOT NULL,
        conceito_id UUID NOT NULL REFERENCES conceitos(id),
        ano VARCHAR(4) NOT NULL,
        mes VARCHAR(2) NOT NULL,
        valor_planeado NUMERIC(15,2) NOT NULL DEFAULT 0,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_orcamentos_company_conceito_ano_mes ON orcamentos (company_id, conceito_id, ano, mes)",
    # UX v2 — Detalhes ricos de movimentos
    "ALTER TABLE movimentos_financeiros ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP",
    "ALTER TABLE movimentos_financeiros ADD COLUMN IF NOT EXISTS closed_by VARCHAR(36)",
    """
    CREATE TABLE IF NOT EXISTS movimento_comentarios (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        movimento_id UUID NOT NULL REFERENCES movimentos_financeiros(id),
        company_id UUID NOT NULL,
        user_id UUID NOT NULL REFERENCES users(id),
        texto TEXT NOT NULL,
        edited_at TIMESTAMP,
        deleted_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_comentarios_movimento ON movimento_comentarios (movimento_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS movimento_anexos (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        movimento_id UUID NOT NULL REFERENCES movimentos_financeiros(id),
        company_id UUID NOT NULL,
        file_path VARCHAR(500) NOT NULL,
        file_name VARCHAR(255) NOT NULL,
        mime_type VARCHAR(100),
        size_bytes INTEGER,
        uploaded_by UUID REFERENCES users(id),
        uploaded_at TIMESTAMP DEFAULT NOW(),
        deleted_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_anexos_movimento ON movimento_anexos (movimento_id, uploaded_at DESC)",
    # Backfill closed_at/closed_by para movimentos já fechados (estimativa: updated_at)
    """
    UPDATE movimentos_financeiros
    SET closed_at = updated_at
    WHERE estado_movimento = 'fechado' AND closed_at IS NULL
    """,
    # v3 — Recuperação de senha
    """
    CREATE TABLE IF NOT EXISTS password_resets (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id),
        token VARCHAR(64) UNIQUE NOT NULL,
        expires_at TIMESTAMP NOT NULL,
        used_at TIMESTAMP,
        ip_address VARCHAR(45),
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_password_resets_user_id ON password_resets (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_password_resets_token ON password_resets (token)",
    # v4 — Auditoria de eliminação de anexos (deleted_by é VARCHAR para alinhar com users.id legado)
    "ALTER TABLE movimento_anexos ADD COLUMN IF NOT EXISTS deleted_by VARCHAR(36)",
    "ALTER TABLE movimento_anexos ADD COLUMN IF NOT EXISTS delete_reason VARCHAR(500)",
    # Caso já exista UUID, converte para VARCHAR
    "ALTER TABLE movimento_anexos ALTER COLUMN deleted_by TYPE VARCHAR(36) USING deleted_by::text",
    "ALTER TABLE movimento_anexos ADD COLUMN IF NOT EXISTS tipo_fatura VARCHAR(20)",
    # v5 — Origem do carregamento do fundo
    "ALTER TABLE fundo_carregamentos ADD COLUMN IF NOT EXISTS origem VARCHAR(50)",
    # v6 — Entidade Cliente + ponte Fornecedor↔Cliente + cliente_id em movimentos
    """
    CREATE TABLE IF NOT EXISTS clientes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        company_id UUID NOT NULL,
        nome VARCHAR(255) NOT NULL,
        nif VARCHAR(20) NOT NULL,
        telefone VARCHAR(20),
        email VARCHAR(255),
        endereco TEXT,
        estado VARCHAR(50) DEFAULT 'ativo',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        deleted_at TIMESTAMP,
        fornecedor_id UUID
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_clientes_company ON clientes (company_id, deleted_at)",
    "CREATE INDEX IF NOT EXISTS ix_clientes_nif ON clientes (company_id, nif) WHERE deleted_at IS NULL",
    "ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS cliente_id UUID",
    "ALTER TABLE movimentos_financeiros ADD COLUMN IF NOT EXISTS cliente_id UUID",
    "CREATE INDEX IF NOT EXISTS ix_movs_cliente ON movimentos_financeiros (cliente_id)",
    "ALTER TABLE movimentos_financeiros ALTER COLUMN fornecedor_id DROP NOT NULL",
    # v7 — Permissões granulares e grupos
    """
    CREATE TABLE IF NOT EXISTS permissoes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        codigo VARCHAR(80) UNIQUE NOT NULL,
        menu VARCHAR(50) NOT NULL,
        acao VARCHAR(50) NOT NULL,
        descricao VARCHAR(255)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_permissoes_menu ON permissoes (menu)",
    """
    CREATE TABLE IF NOT EXISTS grupos (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        company_id UUID NOT NULL,
        nome VARCHAR(60) NOT NULL,
        descricao VARCHAR(255),
        is_system BOOLEAN DEFAULT FALSE NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_grupos_company ON grupos (company_id)",
    """
    CREATE TABLE IF NOT EXISTS grupo_permissoes (
        grupo_id UUID NOT NULL REFERENCES grupos(id) ON DELETE CASCADE,
        permissao_id UUID NOT NULL REFERENCES permissoes(id) ON DELETE CASCADE,
        PRIMARY KEY (grupo_id, permissao_id)
    )
    """,
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS grupo_id UUID",
    # v8 — Hierarquia Módulo > Página > Permissão
    "ALTER TABLE permissoes ADD COLUMN IF NOT EXISTS modulo VARCHAR(50)",
    "CREATE INDEX IF NOT EXISTS ix_permissoes_modulo ON permissoes (modulo)",
    # v9 — Pontes Fornecedor↔Cliente como VARCHAR (alinhamento com restantes IDs legacy)
    "ALTER TABLE fornecedores ALTER COLUMN cliente_id TYPE VARCHAR(36) USING cliente_id::text",
    "ALTER TABLE clientes ALTER COLUMN fornecedor_id TYPE VARCHAR(36) USING fornecedor_id::text",
    "ALTER TABLE movimentos_financeiros ALTER COLUMN cliente_id TYPE VARCHAR(36) USING cliente_id::text",
    # v10 — Tabelas Módulo / Página
    """
    CREATE TABLE IF NOT EXISTS modulos (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        nome VARCHAR(80) UNIQUE NOT NULL,
        descricao VARCHAR(255),
        icone VARCHAR(50),
        ordem INTEGER DEFAULT 0,
        is_system BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS paginas (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        modulo_id VARCHAR(36),
        nome VARCHAR(80) NOT NULL,
        descricao VARCHAR(255),
        href VARCHAR(150),
        icone VARCHAR(50),
        ordem INTEGER DEFAULT 0,
        is_system BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_paginas_modulo ON paginas (modulo_id)",
    "ALTER TABLE permissoes ADD COLUMN IF NOT EXISTS pagina_id VARCHAR(36)",
    "CREATE INDEX IF NOT EXISTS ix_permissoes_pagina ON permissoes (pagina_id)",
    # v11 — Flag para forçar troca de senha no primeiro login
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE NOT NULL",
    # v12 — alinhar users.grupo_id como VARCHAR (consistente com grupos.id varchar)
    "ALTER TABLE users ALTER COLUMN grupo_id TYPE VARCHAR(36) USING grupo_id::text",
    # v13 — sessões e suspensão
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMP",
    # v14 — Catálogo de Origens de Fundo
    """
    CREATE TABLE IF NOT EXISTS origens_fundo (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        company_id VARCHAR(36) NOT NULL,
        nome VARCHAR(80) NOT NULL,
        descricao VARCHAR(255),
        ordem INTEGER DEFAULT 0,
        is_system BOOLEAN DEFAULT FALSE,
        estado VARCHAR(20) DEFAULT 'ativo',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_origens_fundo_company ON origens_fundo (company_id)",
    # v15 — Produtos / Categorias de Produto (KITOKA + base p/ Estoque e Caixa)
    # NOTA: IDs como VARCHAR(36) para alinhar com UUIDType.impl=String(36)
    # do SQLAlchemy (consistente com clientes/fornecedores/etc.). Postgres
    # nativo UUID gera erro "uuid = character varying" no SQLAlchemy.
    """
    CREATE TABLE IF NOT EXISTS produto_categorias (
        id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
        company_id VARCHAR(36) NOT NULL,
        nome VARCHAR(120) NOT NULL,
        ordem INTEGER DEFAULT 0 NOT NULL,
        estado VARCHAR(20) DEFAULT 'ativo',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        deleted_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_produto_categorias_company ON produto_categorias (company_id, deleted_at)",
    """
    CREATE TABLE IF NOT EXISTS produtos (
        id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
        company_id VARCHAR(36) NOT NULL,
        sku VARCHAR(50) NOT NULL,
        nome VARCHAR(255) NOT NULL,
        marca VARCHAR(100),
        categoria_id VARCHAR(36),
        unidade_medida VARCHAR(10) DEFAULT 'un' NOT NULL,
        preco_base NUMERIC(15,2) DEFAULT 0 NOT NULL,
        iva_pct NUMERIC(5,2) DEFAULT 14 NOT NULL,
        descricao TEXT,
        activo BOOLEAN DEFAULT TRUE NOT NULL,
        ref_primavera VARCHAR(50),
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        deleted_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_produtos_company ON produtos (company_id, deleted_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_produtos_company_sku ON produtos (company_id, sku) WHERE deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_produtos_categoria ON produtos (categoria_id)",
    "CREATE INDEX IF NOT EXISTS ix_produtos_ref_primavera ON produtos (ref_primavera)",
    # v16 — Estoque multi-armazém (F2)
    """
    CREATE TABLE IF NOT EXISTS armazens (
        id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
        company_id VARCHAR(36) NOT NULL,
        codigo VARCHAR(20) NOT NULL,
        nome VARCHAR(120) NOT NULL,
        morada TEXT,
        activo BOOLEAN DEFAULT TRUE NOT NULL,
        ref_primavera VARCHAR(50),
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        deleted_at TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_armazens_company ON armazens (company_id, deleted_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_armazens_company_codigo ON armazens (company_id, codigo) WHERE deleted_at IS NULL",
    """
    CREATE TABLE IF NOT EXISTS stock_saldos (
        id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
        company_id VARCHAR(36) NOT NULL,
        produto_id VARCHAR(36) NOT NULL,
        armazem_id VARCHAR(36) NOT NULL,
        qtd_actual NUMERIC(15,3) DEFAULT 0 NOT NULL,
        qtd_reservada NUMERIC(15,3) DEFAULT 0 NOT NULL,
        stock_minimo NUMERIC(15,3) DEFAULT 0 NOT NULL,
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_saldos_produto_armazem ON stock_saldos (produto_id, armazem_id)",
    "CREATE INDEX IF NOT EXISTS ix_stock_saldos_company ON stock_saldos (company_id)",
    """
    CREATE TABLE IF NOT EXISTS stock_movimentos (
        id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
        company_id VARCHAR(36) NOT NULL,
        produto_id VARCHAR(36) NOT NULL,
        armazem_origem_id VARCHAR(36),
        armazem_destino_id VARCHAR(36),
        tipo VARCHAR(30) NOT NULL,
        quantidade NUMERIC(15,3) NOT NULL,
        custo_unitario NUMERIC(15,2),
        documento_ref_tipo VARCHAR(30),
        documento_ref_id VARCHAR(36),
        motivo TEXT,
        estornado_de VARCHAR(36),
        created_by VARCHAR(36),
        created_at TIMESTAMP DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_stock_mov_company ON stock_movimentos (company_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_stock_mov_produto ON stock_movimentos (produto_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_stock_mov_tipo ON stock_movimentos (tipo)",
    # v17 — Caixa / Vendas (F4)
    """
    CREATE TABLE IF NOT EXISTS caixa_sessoes (
        id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
        company_id VARCHAR(36) NOT NULL,
        utilizador_id VARCHAR(36) NOT NULL,
        armazem_id VARCHAR(36) NOT NULL,
        abertura_em TIMESTAMP DEFAULT NOW(),
        fundo_inicial NUMERIC(15,2) DEFAULT 0 NOT NULL,
        fecho_em TIMESTAMP,
        fundo_apurado NUMERIC(15,2),
        fundo_contado NUMERIC(15,2),
        diferenca NUMERIC(15,2),
        observacao TEXT,
        estado VARCHAR(20) DEFAULT 'aberta' NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_caixa_sessoes_company_estado ON caixa_sessoes (company_id, estado)",
    "CREATE INDEX IF NOT EXISTS ix_caixa_sessoes_utilizador ON caixa_sessoes (utilizador_id, estado)",
    """
    CREATE TABLE IF NOT EXISTS vendas (
        id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
        company_id VARCHAR(36) NOT NULL,
        sessao_id VARCHAR(36),
        cliente_id VARCHAR(36),
        armazem_id VARCHAR(36) NOT NULL,
        numero_proforma VARCHAR(30),
        data TIMESTAMP DEFAULT NOW(),
        total_bruto NUMERIC(15,2) DEFAULT 0 NOT NULL,
        total_desconto NUMERIC(15,2) DEFAULT 0 NOT NULL,
        total_iva NUMERIC(15,2) DEFAULT 0 NOT NULL,
        total_liquido NUMERIC(15,2) DEFAULT 0 NOT NULL,
        estado VARCHAR(20) DEFAULT 'rascunho' NOT NULL,
        correlation_id VARCHAR(64) UNIQUE NOT NULL,
        ref_primavera VARCHAR(50),
        primavera_marcada_em TIMESTAMP,
        primavera_marcada_por VARCHAR(36),
        observacao TEXT,
        created_by VARCHAR(36) NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_vendas_company_estado ON vendas (company_id, estado, data DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_vendas_numero_proforma ON vendas (company_id, numero_proforma) WHERE numero_proforma IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_vendas_pendente_primavera ON vendas (company_id) WHERE estado = 'concluida' AND ref_primavera IS NULL",
    """
    CREATE TABLE IF NOT EXISTS venda_linhas (
        id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
        venda_id VARCHAR(36) NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
        produto_id VARCHAR(36) NOT NULL,
        sku_snapshot VARCHAR(50) NOT NULL,
        nome_snapshot VARCHAR(255) NOT NULL,
        quantidade NUMERIC(15,3) NOT NULL,
        preco_unitario NUMERIC(15,2) NOT NULL,
        iva_pct NUMERIC(5,2) DEFAULT 0 NOT NULL,
        desconto_pct NUMERIC(5,2) DEFAULT 0 NOT NULL,
        subtotal NUMERIC(15,2) NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_venda_linhas_venda ON venda_linhas (venda_id)",
    """
    CREATE TABLE IF NOT EXISTS venda_pagamentos (
        id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
        venda_id VARCHAR(36) NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
        forma VARCHAR(20) NOT NULL,
        valor NUMERIC(15,2) NOT NULL,
        ref_externa VARCHAR(120),
        data TIMESTAMP DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_venda_pagamentos_venda ON venda_pagamentos (venda_id)",
    # v18 — Hotfix: converter colunas UUID nativas (v15-v17) para VARCHAR(36)
    # alinhando com UUIDType.impl=String(36) do SQLAlchemy.
    # Idempotente: ALTER...USING falha se já é VARCHAR (apanhado pelo [SKIP]).
    *[
        f'ALTER TABLE "{t}" ALTER COLUMN "{c}" TYPE VARCHAR(36) USING "{c}"::text'
        for t, c in [
            ("produto_categorias", "id"), ("produto_categorias", "company_id"),
            ("produtos", "id"), ("produtos", "company_id"),
            ("armazens", "id"), ("armazens", "company_id"),
            ("stock_saldos", "id"), ("stock_saldos", "company_id"),
            ("stock_saldos", "produto_id"), ("stock_saldos", "armazem_id"),
            ("stock_movimentos", "id"), ("stock_movimentos", "company_id"),
            ("stock_movimentos", "produto_id"),
            ("stock_movimentos", "armazem_origem_id"),
            ("stock_movimentos", "armazem_destino_id"),
            ("stock_movimentos", "estornado_de"), ("stock_movimentos", "created_by"),
            ("caixa_sessoes", "id"), ("caixa_sessoes", "company_id"),
            ("caixa_sessoes", "utilizador_id"), ("caixa_sessoes", "armazem_id"),
            ("vendas", "id"), ("vendas", "company_id"),
            ("vendas", "sessao_id"), ("vendas", "armazem_id"),
            ("vendas", "faturada_por"), ("vendas", "created_by"),
            ("venda_linhas", "id"), ("venda_linhas", "venda_id"),
            ("venda_linhas", "produto_id"),
            ("venda_pagamentos", "id"), ("venda_pagamentos", "venda_id"),
        ]
    ],
    # v19 — Remoção do mecanismo Primavera (sem integração ERP externa
    # neste ciclo; ver SIGES_BI_JENNOS_Documento_Visao_Arquitetural.md
    # Secção 2.4 e PROMPT_SISTEMA_SIGES_SPRINTS.md Sprint 0.2).
    # Colunas ref_primavera/primavera_marcada_* migradas via script dedicado
    # migrar_remover_primavera.py (preserva histórico com ADD+UPDATE+DROP,
    # em vez de RENAME directo, e corre a seguir a este script no arranque).
    "DROP INDEX IF EXISTS ix_produtos_ref_primavera",
    "CREATE INDEX IF NOT EXISTS ix_vendas_pendente_faturacao ON vendas (company_id) WHERE estado = 'concluida' AND numero_fatura_interna IS NULL",
]

def run():
    db_url = _resolve_url()
    if not db_url:
        print("ERRO: Defina DB_URL ou DATABASE_URL")
        sys.exit(1)
    print(f"Ligando à base de dados...")
    try:
        conn = psycopg.connect(db_url)
    except Exception as e:
        print(f"ERRO ao ligar: {e}")
        sys.exit(1)

    conn.autocommit = False
    ok = 0
    for stmt in MIGRATIONS:
        label = stmt.strip().splitlines()[0][:80]
        try:
            with conn.transaction():
                conn.execute(stmt)
            print(f"  [OK] {label}")
            ok += 1
        except Exception as e:
            print(f"  [SKIP] {label}")
            print(f"    → {e}")

    conn.close()
    print(f"\nMigração concluída: {ok}/{len(MIGRATIONS)} instruções executadas.")

if __name__ == "__main__":
    run()
