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

## Fase 2 — Requer campo novo: timestamps por transição de estado

**Bloqueia:** Tempo Médio por Lavagem, Tempo de Espera na Fila, Tempo Médio de Atendimento (check-in → entrega), Eficiência Operacional (lavagens/hora), Produtividade por Turno.

### Problema actual

`OrdemLavagemModel.updated_at` é sobrescrito a cada mudança de estado (`checkin`, `iniciar`, `controlo_qualidade`, `concluir` fazem todos `o.updated_at = datetime.utcnow()`). É impossível hoje reconstruir quando ocorreu o check-in especificamente — cada transição apaga o timestamp da anterior.

### Especificação

- [ ] Adicionar a `OrdemLavagemModel`: `checkin_em` (DateTime, nullable), `iniciado_em` (DateTime, nullable), `controlo_qualidade_em` (DateTime, nullable), `concluido_em` (DateTime, nullable). Migração idempotente em `migrar_*.py` com `ADD COLUMN IF NOT EXISTS`.
- [ ] `operacoes_lavagem.py`: cada endpoint de transição (`/checkin`, `/iniciar`, `/controlo-qualidade`, `/concluir`) preenche o timestamp correspondente, além de continuar a actualizar `updated_at`.
- [ ] Novo indicador `GET /bi/dashboards/operacional` → `lavagem_tempo_medio_atendimento_minutos`: média de `(concluido_em - checkin_em)` sobre ordens concluídas no período.
- [ ] Novo indicador `lavagem_tempo_medio_espera_minutos`: para ordens ainda em `agendada`/`checkin`, `(agora - created_at)` — tempo de espera na fila.
- [ ] Produtividade por hora/turno passa a ser possível agrupando `checkin_em`/`concluido_em` por hora do dia — especificar endpoint `GET /bi/dashboards/operacional/produtividade-horaria?data=` quando este sprint avançar.

**Critério de aceitação:** criar uma ordem, fazer check-in, iniciar e concluir com um intervalo real (ex.: 40 min) faz `lavagem_tempo_medio_atendimento_minutos` reflectir esse valor.

---

## Fase 3 — Requer preço persistido na ordem

**Bloqueia:** Ticket Médio, Receita da Lavagem, Receita por Box/Equipa/Funcionário/Produto, Ranking de Serviços por rentabilidade, Valor por Cliente, Lifetime Value.

### Problema actual

O preço de uma `OrdemLavagem` é **calculado dinamicamente** via `_calcular_preco_ordem` (tipo + categoria + extras) sempre que é pedido — nunca fica persistido na própria ordem. Isto obriga a recalcular por ordem em toda agregação de receita, o que é caro e frágil se o catálogo de preços mudar depois.

### Especificação

- [ ] Adicionar `OrdemLavagemModel.preco_total_snapshot` (Numeric, nullable) — preenchido no momento da conclusão (`POST /ordens/{id}/concluir`), com o valor calculado por `_calcular_preco_ordem` **nesse instante**, para não mudar retroactivamente se o catálogo for alterado depois.
- [ ] Novos indicadores agregados sobre `preco_total_snapshot`: receita total do dia/semana/mês, ticket médio, receita por box (via `box_id`), receita por equipa (via `equipa` CSV), receita por tipo de serviço.

**Critério de aceitação:** concluir uma lavagem grava o preço nesse momento; mudar o `preco_base` do `TipoLavagem` depois não altera o valor já gravado nas ordens antigas.

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
Fase 2 (timestamps por estado)     — desbloqueia tempo médio, eficiência, produtividade por turno
   ↓
Fase 3 (preço persistido)          — desbloqueia receita/ticket médio/rentabilidade
   ↓
Fase 4 (decisão de negócio)        — produtividade individual, só depois de confirmar o modelo
Fase 5 (Filial)                    — só se houver mais de uma unidade física
   ↓
Fase 6 (heatmap, cross-sell)       — construir sobre as fases anteriores já maduras
IA de previsão                     — fora de escopo até decisão de negócio explícita
```

Cada fase é autossuficiente para ser copiada como prompt isolado.
