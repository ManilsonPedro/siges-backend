# PROMPT — Dashboard Executivo: Centro de Inteligência Operacional (Lavagem)

> Copiar este documento inteiro (ou o sprint específico) como prompt para a sessão de IA que vai implementar o código.
> Complementa `PROMPT_SISTEMA_SIGES_SPRINTS.md` (Sprint 8, BI & Fecho). Este documento detalha especificamente a
> especificação de "Centro de Comando Operacional" para o módulo de Lavagem — o core business do SIGES.

---

## Regras Fixas (idênticas a `PROMPT_SISTEMA_SIGES_SPRINTS.md`)

- Stack: Python 3.11 + FastAPI + SQLAlchemy 2 Async + PostgreSQL, sem Alembic (`migrar.py` + scripts idempotentes).
- Reutilizar RBAC (`dashboard.ver`), Auditoria, Soft-delete.
- **Nenhum KPI pode ser inventado.** Se o dado não existir na BD, o indicador fica de fora até o schema suportar — nunca um valor fixo/mock (o próprio `bi.py` já declara este princípio no cabeçalho).

---

## Contexto

O pedido original ("Dashboard Executivo SIGES — Operações") propõe ~40 indicadores para o módulo de Lavagem: KPIs, produtividade por hora/dia/semana/mês/box/equipa/funcionário/turno, rankings de serviços e clientes, receita por múltiplas dimensões, tempo de atendimento, consumo, alertas operacionais, e sugestões avançadas (heatmap, retrabalho, no-show, cross-selling, LTV, comparativo entre filiais, previsão por IA).

Uma auditoria ao schema actual (`app/infrastructure/database/models.py`) confirmou que **parte destes indicadores já é calculável hoje** e parte **exige campos/tabelas novas** que não existem. Este documento separa isso em fases.

## Fase 1 — Já implementada (`GET /bi/dashboards/operacional`)

Estes indicadores já estão no backend e ligados ao Dashboard Executivo:

- Lavagens hoje / agendadas hoje / concluídas hoje
- Lavagens em curso (checkin/em_curso/controlo_qualidade)
- Walk-ins hoje vs. reservas hoje
- Taxa de ocupação de boxes (tempo real)
- Água consumida por categoria de veículo
- Top 5 clientes por nº de lavagens concluídas (histórico completo)
- Avaliação média de qualidade (1-5, todas as ordens)
- Cancelamentos hoje
- Taxa de retrabalho (% de ordens concluídas com `re_lavagem_de_id` preenchido)
- Top 5 extras mais vendidos (por contagem)

**Critério de aceitação:** já cumprido — ver `bi.py::dashboard_operacional` e `dashboard/relatorios/executivo/page.tsx`.

---

## Fase 2 — Concluída: timestamps por transição de estado

**Desbloqueou:** Tempo Médio de Atendimento (check-in → conclusão), Tempo Médio de Espera na Fila.
**Ainda por fazer dentro desta fase:** Eficiência Operacional (lavagens/hora), Produtividade por Turno, Heatmap — ver nota abaixo.

### O que foi implementado

- `OrdemLavagemModel` ganhou `checkin_em`, `iniciado_em`, `controlo_qualidade_em`, `concluido_em` (todos `DateTime`, nullable) — `updated_at` continua a ser sobrescrito a cada transição (comportamento antigo preservado), mas agora cada transição também grava o seu próprio timestamp dedicado, que nunca é apagado por uma transição posterior.
- Migração idempotente em `migrar_dashboard_lavagem.py` (`ADD COLUMN IF NOT EXISTS`), registada em `migrar.py`.
- `operacoes_lavagem.py`: `/checkin`, `/iniciar`, `/controlo-qualidade`, `/concluir` preenchem o timestamp correspondente.
- `GET /bi/dashboards/operacional` → `lavagem_tempo_medio_atendimento_minutos` (média de `concluido_em - checkin_em` sobre ordens com ambos preenchidos) e `lavagem_tempo_medio_espera_minutos` (média de `agora - created_at` sobre ordens ainda em `agendada`/`confirmada`/`checkin`).
- Ligado ao Dashboard Executivo (`dashboard/relatorios/executivo/page.tsx`).

### Ainda por fazer (não incluído nesta implementação)

- [ ] Produtividade por hora/turno: agrupar `checkin_em`/`concluido_em` por hora do dia — especificar endpoint `GET /bi/dashboards/operacional/produtividade-horaria?data=` quando este sprint avançar. Não implementado porque exige decidir a granularidade de agrupamento (por hora civil? por turno operacional?) antes de codificar.

**Critério de aceitação:** cumprido para tempo médio de atendimento/espera — testar criando uma ordem, fazendo check-in, iniciar e concluir com um intervalo real (ex.: 40 min) e confirmando que `lavagem_tempo_medio_atendimento_minutos` reflecte esse valor.

---

## Fase 3 — Concluída: preço persistido na ordem

**Desbloqueou:** Ticket Médio da Lavagem, Receita da Lavagem (hoje/total).
**Ainda por fazer dentro desta fase:** Receita por Box/Equipa/Funcionário/Produto, Ranking de Serviços por rentabilidade — ver nota abaixo.

### O que foi implementado

- `OrdemLavagemModel.preco_total_snapshot` (Numeric(10,2), nullable) — preenchido em `POST /ordens/{id}/concluir` com o valor calculado por `_calcular_preco_ordem` **nesse instante** (tipo + categoria do veículo + extras vigentes), antes de a ordem passar a `concluida`. Não muda retroactivamente se o catálogo de preços for alterado depois.
- `_to_response` em `operacoes_lavagem.py` usa `preco_total_snapshot` quando já preenchido (ordem concluída/paga) em vez de recalcular pelo catálogo actual — histórico fica estável.
- `GET /bi/dashboards/operacional` → `lavagem_receita_total`, `lavagem_receita_hoje`, `lavagem_ticket_medio` (todos sobre `preco_total_snapshot`, só ordens já concluídas).
- Ligado ao Dashboard Executivo.

### Ainda por fazer (não incluído nesta implementação)

- [ ] Receita por Box: agrupar `preco_total_snapshot` por `box_id`.
- [ ] Receita por Equipa: agrupar por `equipa` (CSV de user_id) — exige parsear o CSV ou aguardar decisão da Fase 4 sobre atribuição individual.
- [ ] Receita por Tipo de Serviço: agrupar por `tipo_lavagem_id`.
- [ ] Ranking de Serviços por rentabilidade: depende de custo por serviço, que não existe no schema (só `preco_base`, sem custo associado) — precisa de decisão de negócio sobre como modelar custo antes de avançar.

Não implementados nesta passagem por serem "mais uma dimensão de agrupamento" sobre a mesma coluna, não um bloqueio de schema — podem ser adicionados a pedido, individualmente, sem necessidade de mais migrações.

**Critério de aceitação:** cumprido para ticket médio/receita — concluir uma lavagem grava o preço nesse momento; mudar o `preco_base` do `TipoLavagem` depois não altera o valor já gravado nas ordens antigas.

---

## Fase 4 — Requer atribuição individual (não só CSV de equipa)

**Bloqueia:** Produtividade por Funcionário (ranking individual), Tempo Médio por Funcionário, Avaliação por Colaborador.

### Problema actual

`OrdemLavagemModel.equipa` é uma string CSV de `user_id` da equipa inteira escalada para o box/turno — não identifica **qual colaborador** especificamente lavou aquele carro dentro da equipa.

### Especificação (decisão de negócio necessária antes de implementar)

Duas opções, a escolher com o utilizador antes deste sprint avançar:
1. Manter equipa colectiva (como hoje) e reportar produtividade só ao nível de equipa/box, nunca individual.
2. Adicionar um campo opcional `OrdemLavagemModel.colaborador_responsavel_id` preenchido manualmente pelo operador no check-in/início, para permitir ranking individual sem reestruturar o conceito de equipa.

**Não avançar esta fase sem essa decisão.**

---

## Fase 5 — Requer entidade `Filial`

**Bloqueia:** Comparativo entre Filiais.

### Problema actual

Não existe `FilialModel`/tabela `filiais` no schema — só um campo solto `filial_id` em `AreaServicoModel`, sem entidade correspondente nem propagação a `BoxLavagemModel`/`OrdemLavagemModel`/`EquipaLavagemModel`.

### Especificação

- [ ] Criar `FilialModel` (id, company_id, nome, morada, activo) — já previsto em `PROMPT_DOMINIO_01_OPERACOES.md`.
- [ ] Propagar `filial_id` a `BoxLavagemModel` (via `AreaServicoModel`, já tem a FK) e agregações por filial.
- [ ] Este sprint só compensa se a empresa tiver mais do que uma unidade física — confirmar necessidade de negócio antes de implementar.

---

## Fase 6 — Indicadores que exigem novo conceito de negócio (fora do schema actual)

Estes itens do pedido original não têm nenhum dado subjacente hoje — são **funcionalidades novas**, não relatórios sobre dados existentes:

- **Heatmap de Movimento**: exige agregação por hora×dia-da-semana — depende da Fase 2 (timestamps).
- **No-Show** (distinto de cancelamento): exige um estado/flag próprio para "cliente reservou e não apareceu", que hoje não existe (só há `cancelada`, que pode ser cancelamento activo do cliente ou não-comparência — sem distinção). Adicionar `estado = "no_show"` ou flag booleana se este KPI for aprovado.
- **Conversão / Cross-selling** (lavagem → loja → restaurante → bar): exige cruzar `OrdemLavagemModel.cliente_id` com `VendaModel`/`ComandaModel` do mesmo cliente no mesmo dia — possível hoje sem campos novos, mas é uma agregação cara (múltiplos joins); especificar como endpoint dedicado, não no dashboard principal.
- **Valor por Cliente / Lifetime Value**: parcialmente coberto por `GET /clientes/historico-comercial` (Sprint 1 de `PROMPT_SISTEMA_SIGES_SPRINTS.md`) — falta só expor "receita total / nº clientes" como indicador agregado no dashboard executivo.
- **Previsão de Procura (IA)**: fora de escopo deste ciclo — exige decisão de negócio sobre que modelo/serviço usar (não implementar sem essa decisão explícita).

---

## Ordem de execução recomendada

```
Fase 1 (concluída, incluindo cancelamentos/retrabalho/extras)
   ↓
Fase 2 (concluída: tempo médio de atendimento/espera — produtividade por turno ainda por especificar)
   ↓
Fase 3 (concluída: ticket médio/receita — receita por box/equipa/serviço ainda por adicionar)
   ↓
Fase 4 (decisão de negócio)        — produtividade individual, só depois de confirmar o modelo
Fase 5 (Filial)                    — só se houver mais de uma unidade física
   ↓
Fase 6 (heatmap, cross-sell)       — construir sobre as fases anteriores já maduras
IA de previsão                     — fora de escopo até decisão de negócio explícita
```

Cada fase é autossuficiente para ser copiada como prompt isolado.
