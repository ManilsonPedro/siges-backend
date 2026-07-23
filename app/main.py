from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from sqlalchemy import text as sql_text
from app.config import settings
from app.infrastructure.database import init_db, engine
from app.presentation.api.v1 import (
    auth_router,
    fornecedor_router,
    cliente_router,
    conceito_router,
    fundo_router,
    movimento_router,
    relatorios_router,
    relatorios_comercial_router,
    company_settings_router,
    search_router,
    saved_filters_router,
    trash_router,
    periodos_router,
    pagamentos_router,
    intelligence_router,
    movimento_detail_router,
    password_reset_router,
    extrato_router,
    permissoes_router,
    modulos_router,
    origens_fundo_router,
    produtos_router,
    armazens_router,
    estoque_router,
    caixa_router,
    localizacoes_router,
    inventarios_router,
    requisicoes_router,
    pedidos_compra_router,
    recepcoes_router,
    fornecedores_avaliacao_router,
    promocoes_router,
    devolucoes_router,
    ecommerce_router,
    operacoes_estacao_router,
    operacoes_lavagem_router,
    operacoes_agua_router,
    portal_auth_router,
    portal_reservas_router,
    restauracao_base_router,
    restauracao_bar_router,
    restauracao_restaurante_router,
    restauracao_churrasqueira_router,
    crm_router,
    marketing_router,
    atendimento_router,
    financeiro_tesouraria_router,
    financeiro_gestao_router,
    contabilidade_router,
    fiscalidade_router,
    rh_router,
    rh_tempo_router,
    rh_avaliacao_router,
    rh_payroll_router,
    bi_router,
    bi_lavagem_avancado_router,
    anexos_router,
    bi_agua_router,
)
import logging
import os

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando aplicação...")
    await init_db()
    # Each migration runs in its own transaction so a failure in one doesn't abort the others.
    # IF NOT EXISTS prevents errors on PostgreSQL when the column already exists.
    for stmt in [
        "ALTER TABLE fundos ADD COLUMN IF NOT EXISTS tipo VARCHAR(10) DEFAULT 'BCS'",
        "ALTER TABLE movimentos_financeiros ADD COLUMN IF NOT EXISTS fundo_tipo VARCHAR(10) DEFAULT 'BCS'",
        "ALTER TABLE movimentos_financeiros ADD COLUMN IF NOT EXISTS codigo VARCHAR(20)",
        "ALTER TABLE movimentos_financeiros ADD COLUMN IF NOT EXISTS estado_movimento VARCHAR(20) DEFAULT 'criado'",
    ]:
        try:
            async with engine.begin() as _conn:
                await _conn.execute(sql_text(stmt))
        except Exception:
            pass
    try:
        async with engine.begin() as _conn:
            await _conn.execute(sql_text("""
                UPDATE movimentos_financeiros
                SET estado_movimento = CASE
                    WHEN estado_pagamento IN ('pago', 'pago_total') THEN 'fechado'
                    WHEN estado_pagamento IN ('pendente', 'pago_parcial') THEN 'pendente'
                    ELSE 'criado'
                END
                WHERE estado_movimento IS NULL OR estado_movimento = 'criado'
            """))
    except Exception:
        pass
    # Backfill any NULL tipo values to 'BCS' (default) so queries by tipo find the row
    try:
        async with engine.begin() as _conn:
            await _conn.execute(sql_text("UPDATE fundos SET tipo = 'BCS' WHERE tipo IS NULL"))
            await _conn.execute(sql_text("UPDATE movimentos_financeiros SET fundo_tipo = 'BCS' WHERE fundo_tipo IS NULL"))
    except Exception:
        pass
    # Remove duplicate fundos per (company_id, tipo) — reassign carregamentos to the kept row first
    try:
        async with engine.begin() as _conn:
            await _conn.execute(sql_text("""
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
            """))
            await _conn.execute(sql_text("""
                DELETE FROM fundos
                WHERE id NOT IN (
                    SELECT DISTINCT ON (company_id, tipo) id
                    FROM fundos
                    ORDER BY company_id, tipo, updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                )
            """))
    except Exception:
        pass
    # Unique constraint on (company_id, tipo) to prevent future duplicates
    try:
        async with engine.begin() as _conn:
            await _conn.execute(sql_text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_fundos_company_tipo ON fundos (company_id, tipo)"
            ))
    except Exception:
        pass
    # Drop legacy UNIQUE index on company_id alone (it blocks having BCS + BFA for same company)
    try:
        async with engine.begin() as _conn:
            await _conn.execute(sql_text("DROP INDEX IF EXISTS ix_fundos_company_id"))
            await _conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_fundos_company_id ON fundos (company_id)"))
    except Exception:
        pass
    os.makedirs(settings.storage_path, exist_ok=True)

    # ─── Migrações e seeds via scripts (idempotentes) ─────────────────────
    # Render free não tem Shell; corremos automaticamente no arranque.
    try:
        import asyncio as _asyncio
        import sys as _sys
        from pathlib import Path as _Path
        # Adicionar a pasta backend ao sys.path para imports dos scripts top-level
        _backend_dir = str(_Path(__file__).resolve().parent.parent)
        if _backend_dir not in _sys.path:
            _sys.path.insert(0, _backend_dir)

        # Garantir que os scripts vêem o DB URL (Render injecta DATABASE_URL)
        if not os.environ.get("DB_URL") and os.environ.get("DATABASE_URL"):
            os.environ["DB_URL"] = os.environ["DATABASE_URL"]
        elif not os.environ.get("DB_URL"):
            os.environ["DB_URL"] = str(settings.database_url)

        from migrate import run as _run_migrate
        from migrar import run as _run_migrar_extra
        from seed_permissoes import run as _run_seed_perm
        from seed_modulos import run as _run_seed_mod
        from seed_produtos import run as _run_seed_produtos

        async def _bootstrap():
            await _asyncio.to_thread(_run_migrate)
            await _asyncio.to_thread(_run_migrar_extra)
            await _asyncio.to_thread(_run_seed_perm)
            await _asyncio.to_thread(_run_seed_mod)
            await _asyncio.to_thread(_run_seed_produtos)

        try:
            await _bootstrap()
            logger.info("Migrações + seeds executados com sucesso no arranque")
        except SystemExit:
            logger.warning("Scripts de migração tentaram exit; ignorado")
        except Exception as e:
            logger.exception(f"Erro em migrate/seed no arranque: {e}")
    except Exception as e:
        logger.exception(f"Erro inesperado no bootstrap: {e}")
    logger.info("Base de dados inicializada")

    from app.infrastructure.scheduler import iniciar_scheduler, parar_scheduler
    iniciar_scheduler()

    yield

    parar_scheduler()
    logger.info("Encerrando aplicação...")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    # Aceita qualquer subdomain *.vercel.app (preview deployments) além das origens explícitas
    allow_origin_regex=r"^https://([a-z0-9-]+\.)*vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    tb = traceback.format_exc()
    print(f"\n{'='*60}\n!!! ERRO em {request.method} {request.url.path}\n{tb}{'='*60}\n", flush=True)
    logger.error(f"Unhandled error em {request.url.path}: {exc}", exc_info=True)
    # Adicionar CORS headers ao erro para o browser conseguir lê-lo
    origin = request.headers.get("origin", "")
    headers = {}
    if origin in settings.allowed_origins or "*" in settings.allowed_origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return JSONResponse(
        status_code=500,
        content={"detail": f"Erro interno: {type(exc).__name__}: {str(exc)[:200]}"},
        headers=headers,
    )


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "debug": settings.debug,
    }


@app.get("/metrics")
async def metrics():
    return {"version": settings.app_version, "environment": settings.environment}


app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(fornecedor_router, prefix="/api/v1/fornecedores", tags=["Fornecedores"])
app.include_router(cliente_router, prefix="/api/v1/clientes", tags=["Clientes"])
app.include_router(conceito_router, prefix="/api/v1/conceitos", tags=["Conceitos"])
app.include_router(fundo_router, prefix="/api/v1/fundos", tags=["Fundos"])
app.include_router(movimento_router, prefix="/api/v1/movimentos", tags=["Movimentos"])
app.include_router(relatorios_router, prefix="/api/v1/relatorios", tags=["Relatórios"])
app.include_router(relatorios_comercial_router, prefix="/api/v1/relatorios", tags=["Relatórios · Comercial"])
app.include_router(company_settings_router, prefix="/api/v1/settings/company", tags=["Configurações"])
app.include_router(search_router, prefix="/api/v1/search", tags=["Search"])
app.include_router(saved_filters_router, prefix="/api/v1/saved-filters", tags=["Filtros Guardados"])
app.include_router(trash_router, prefix="/api/v1/trash", tags=["Lixeira"])
app.include_router(periodos_router, prefix="/api/v1/periodos", tags=["Períodos"])
app.include_router(pagamentos_router, prefix="/api/v1/pagamentos", tags=["Pagamentos Parciais"])
app.include_router(intelligence_router, prefix="/api/v1/intelligence", tags=["Inteligência Financeira"])
app.include_router(movimento_detail_router, prefix="/api/v1/movimentos-detail", tags=["Movimentos · Detalhes"])
app.include_router(password_reset_router, prefix="/api/v1/auth", tags=["Auth · Password Reset"])
app.include_router(extrato_router, prefix="/api/v1/extrato", tags=["Extratos"])
app.include_router(permissoes_router, prefix="/api/v1", tags=["Permissões"])
app.include_router(modulos_router, prefix="/api/v1", tags=["Módulos & Páginas"])
app.include_router(origens_fundo_router, prefix="/api/v1/origens-fundo", tags=["Origens de Fundo"])
app.include_router(produtos_router, prefix="/api/v1/produtos", tags=["Produtos"])
app.include_router(armazens_router, prefix="/api/v1/armazens", tags=["Armazéns"])
app.include_router(estoque_router, prefix="/api/v1/estoque", tags=["Estoque"])
app.include_router(caixa_router, prefix="/api/v1/caixa", tags=["Caixa · Vendas"])
app.include_router(localizacoes_router, prefix="/api/v1/estoque/localizacoes", tags=["Estoque · Localizações"])
app.include_router(inventarios_router, prefix="/api/v1/estoque/inventarios", tags=["Estoque · Inventários"])
app.include_router(requisicoes_router, prefix="/api/v1/compras/requisicoes", tags=["Compras · Requisições"])
app.include_router(pedidos_compra_router, prefix="/api/v1/compras/pedidos", tags=["Compras · Pedidos"])
app.include_router(recepcoes_router, prefix="/api/v1/compras/recepcoes", tags=["Compras · Receções"])
app.include_router(fornecedores_avaliacao_router, prefix="/api/v1/fornecedores", tags=["Fornecedores · Contratos & Avaliação"])
app.include_router(promocoes_router, prefix="/api/v1/loja/promocoes", tags=["Loja · Promoções"])
app.include_router(devolucoes_router, prefix="/api/v1/caixa/devolucoes", tags=["Caixa · Devoluções"])
app.include_router(ecommerce_router, prefix="/api/v1/ecommerce", tags=["E-Commerce"])
app.include_router(operacoes_estacao_router, prefix="/api/v1/operacoes/estacao", tags=["Operações · Estação"])
app.include_router(operacoes_lavagem_router, prefix="/api/v1/operacoes/lavagem", tags=["Operações · Lavagem"])
app.include_router(operacoes_agua_router, prefix="/api/v1/operacoes/agua", tags=["Operações · Água"])
app.include_router(portal_auth_router, prefix="/api/v1/portal/auth", tags=["Portal do Cliente · Auth"])
app.include_router(portal_reservas_router, prefix="/api/v1/portal", tags=["Portal do Cliente · Reservas"])
app.include_router(restauracao_base_router, prefix="/api/v1/restauracao", tags=["Restauração · Base"])
app.include_router(restauracao_bar_router, prefix="/api/v1/restauracao/bar", tags=["Restauração · Bar"])
app.include_router(restauracao_restaurante_router, prefix="/api/v1/restauracao/restaurante", tags=["Restauração · Restaurante"])
app.include_router(restauracao_churrasqueira_router, prefix="/api/v1/restauracao/churrasqueira", tags=["Restauração · Churrasqueira"])
app.include_router(crm_router, prefix="/api/v1/crm", tags=["CRM"])
app.include_router(marketing_router, prefix="/api/v1/marketing", tags=["Marketing"])
app.include_router(atendimento_router, prefix="/api/v1/atendimento", tags=["Atendimento"])
app.include_router(financeiro_tesouraria_router, prefix="/api/v1/financeiro", tags=["Financeiro · Tesouraria"])
app.include_router(financeiro_gestao_router, prefix="/api/v1/financeiro", tags=["Financeiro · Gestão"])
app.include_router(contabilidade_router, prefix="/api/v1/contabilidade", tags=["Contabilidade"])
app.include_router(fiscalidade_router, prefix="/api/v1/fiscalidade", tags=["Fiscalidade"])
app.include_router(rh_router, prefix="/api/v1/rh", tags=["RH"])
app.include_router(rh_tempo_router, prefix="/api/v1/rh", tags=["RH · Tempo"])
app.include_router(rh_avaliacao_router, prefix="/api/v1/rh/avaliacao", tags=["RH · Avaliação"])
app.include_router(rh_payroll_router, prefix="/api/v1/rh/payroll", tags=["RH · Payroll"])
app.include_router(bi_router, prefix="/api/v1/bi", tags=["BI & Analytics"])
app.include_router(bi_lavagem_avancado_router, prefix="/api/v1/bi", tags=["BI & Analytics · Lavagem Avançado"])
app.include_router(anexos_router, prefix="/api/v1/anexos", tags=["Anexos"])
app.include_router(bi_agua_router, prefix="/api/v1/bi", tags=["BI & Analytics · Água"])

uploads_path = settings.storage_path
os.makedirs(uploads_path, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_path), name="uploads")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
