from app.presentation.api.v1.auth import router as auth_router
from app.presentation.api.v1.fornecedor import router as fornecedor_router
from app.presentation.api.v1.cliente import router as cliente_router
from app.presentation.api.v1.conceito import router as conceito_router
from app.presentation.api.v1.fundo import router as fundo_router
from app.presentation.api.v1.movimento import router as movimento_router
from app.presentation.api.v1.relatorios import router as relatorios_router
from app.presentation.api.v1.relatorios_comercial import router as relatorios_comercial_router
from app.presentation.api.v1.company_settings import router as company_settings_router
from app.presentation.api.v1.search import router as search_router
from app.presentation.api.v1.saved_filters import router as saved_filters_router
from app.presentation.api.v1.trash import router as trash_router
from app.presentation.api.v1.periodos import router as periodos_router
from app.presentation.api.v1.pagamentos import router as pagamentos_router
from app.presentation.api.v1.intelligence import router as intelligence_router
from app.presentation.api.v1.movimento_detail import router as movimento_detail_router
from app.presentation.api.v1.password_reset import router as password_reset_router
from app.presentation.api.v1.extrato import router as extrato_router
from app.presentation.api.v1.permissoes import router as permissoes_router
from app.presentation.api.v1.modulos import router as modulos_router
from app.presentation.api.v1.origens_fundo import router as origens_fundo_router
from app.presentation.api.v1.produtos import router as produtos_router
from app.presentation.api.v1.armazens import router as armazens_router
from app.presentation.api.v1.estoque import router as estoque_router
from app.presentation.api.v1.caixa import router as caixa_router
from app.presentation.api.v1.localizacoes import router as localizacoes_router
from app.presentation.api.v1.inventarios import router as inventarios_router
from app.presentation.api.v1.requisicoes import router as requisicoes_router
from app.presentation.api.v1.pedidos_compra import router as pedidos_compra_router
from app.presentation.api.v1.recepcoes import router as recepcoes_router
from app.presentation.api.v1.fornecedores_avaliacao import router as fornecedores_avaliacao_router
from app.presentation.api.v1.promocoes import router as promocoes_router
from app.presentation.api.v1.devolucoes import router as devolucoes_router
from app.presentation.api.v1.ecommerce import router as ecommerce_router
from app.presentation.api.v1.operacoes_estacao import router as operacoes_estacao_router
from app.presentation.api.v1.operacoes_lavagem import router as operacoes_lavagem_router
from app.presentation.api.v1.operacoes_agua import router as operacoes_agua_router
from app.presentation.api.v1.portal_auth import router as portal_auth_router
from app.presentation.api.v1.portal_reservas import router as portal_reservas_router
from app.presentation.api.v1.restauracao_base import router as restauracao_base_router
from app.presentation.api.v1.restauracao_bar import router as restauracao_bar_router
from app.presentation.api.v1.restauracao_restaurante import router as restauracao_restaurante_router
from app.presentation.api.v1.restauracao_churrasqueira import router as restauracao_churrasqueira_router
from app.presentation.api.v1.crm import router as crm_router
from app.presentation.api.v1.marketing import router as marketing_router
from app.presentation.api.v1.atendimento import router as atendimento_router
from app.presentation.api.v1.financeiro_tesouraria import router as financeiro_tesouraria_router
from app.presentation.api.v1.financeiro_gestao import router as financeiro_gestao_router
from app.presentation.api.v1.contabilidade import router as contabilidade_router
from app.presentation.api.v1.fiscalidade import router as fiscalidade_router
from app.presentation.api.v1.rh import router as rh_router
from app.presentation.api.v1.rh_tempo import router as rh_tempo_router
from app.presentation.api.v1.rh_avaliacao import router as rh_avaliacao_router
from app.presentation.api.v1.rh_payroll import router as rh_payroll_router
from app.presentation.api.v1.bi import router as bi_router
from app.presentation.api.v1.bi_lavagem_avancado import router as bi_lavagem_avancado_router
from app.presentation.api.v1.anexos import router as anexos_router
from app.presentation.api.v1.bi_agua import router as bi_agua_router
from app.presentation.api.v1.brevo_conversations import router as brevo_conversations_router

__all__ = [
    "auth_router",
    "fornecedor_router",
    "cliente_router",
    "conceito_router",
    "fundo_router",
    "movimento_router",
    "relatorios_router",
    "relatorios_comercial_router",
    "company_settings_router",
    "search_router",
    "saved_filters_router",
    "trash_router",
    "periodos_router",
    "pagamentos_router",
    "intelligence_router",
    "movimento_detail_router",
    "password_reset_router",
    "extrato_router",
    "permissoes_router",
    "modulos_router",
    "origens_fundo_router",
    "produtos_router",
    "armazens_router",
    "estoque_router",
    "caixa_router",
    "localizacoes_router",
    "inventarios_router",
    "requisicoes_router",
    "pedidos_compra_router",
    "recepcoes_router",
    "fornecedores_avaliacao_router",
    "promocoes_router",
    "devolucoes_router",
    "ecommerce_router",
    "operacoes_estacao_router",
    "operacoes_lavagem_router",
    "operacoes_agua_router",
    "portal_auth_router",
    "portal_reservas_router",
    "restauracao_base_router",
    "restauracao_bar_router",
    "restauracao_restaurante_router",
    "restauracao_churrasqueira_router",
    "crm_router",
    "marketing_router",
    "atendimento_router",
    "financeiro_tesouraria_router",
    "financeiro_gestao_router",
    "contabilidade_router",
    "fiscalidade_router",
    "rh_router",
    "rh_tempo_router",
    "rh_avaliacao_router",
    "rh_payroll_router",
    "bi_router",
    "bi_lavagem_avancado_router",
    "anexos_router",
    "bi_agua_router",
    "brevo_conversations_router",
]
