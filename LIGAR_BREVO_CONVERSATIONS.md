# Ligar respostas dos clientes ao Brevo Conversations

Objectivo: quando um cliente responde ao email de lembrete de reserva (ou a
qualquer outro email transacional enviado pelo SIGES), essa resposta deve
cair numa caixa de entrada humana partilhada — o Brevo Conversations — em
vez de ficar perdida numa mailbox sem ninguém a monitorizar.

## Isto não é trabalho de código

O envio de email hoje (`app/infrastructure/email/__init__.py`) usa **SMTP
genérico** (por omissão `smtp-mail.outlook.com`, configurável via
`SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM_EMAIL`), não a API de
Email da Brevo. O Brevo Conversations é um produto separado dentro da
mesma plataforma Brevo — não existe nenhuma API que ligue automaticamente
"resposta a um email transacional específico" a uma conversa. A ligação
real é feita ao nível da conta, conectando a **mesma caixa de correio**
usada como remetente (`SMTP_FROM_EMAIL`) como mailbox do Conversations.

Investigação feita (Julho 2026) confirmou:
- Conversations tem canal de email por **forwarding/conexão de mailbox**
  (Gmail, Microsoft 365, ou forwarding manual de outro provedor) — não por
  API. Ver `help.brevo.com` → *Connect and set up your team mailbox in
  Conversations*.
- Ao responder a partir do Conversations, o email sai por defeito de um
  endereço `brevo-mail.com`, a menos que se configure SMTP próprio com o
  domínio real do SIGES.
- A API pública de Conversations (`developers.brevo.com`) é orientada ao
  canal de chat/widget (`visitor`/`agent`), não tem endpoint para "criar
  conversa a partir de um email recebido arbitrário".
- Utilizadores da comunidade Brevo relataram problemas de TLS ao ligar
  caixas fora de Google/Microsoft — testar antes de depender disto em
  produção.

## Passos manuais (painel Brevo, não neste repositório)

1. Confirmar qual é a mailbox real de produção: valor de `SMTP_FROM_EMAIL`
   (ou `SMTP_USER` se aquele não estiver definido) na configuração do
   Render/ambiente de produção do `siges-backend`.
2. Entrar em Brevo → **Conversations** → **Settings** → **Inbox** → **Email**
   → *Connect a mailbox*.
3. Ligar essa mesma caixa (via OAuth se for Gmail/Microsoft 365, ou via
   forwarding manual se for outro provedor).
4. Configurar SMTP próprio da caixa para que as respostas dos agentes
   saiam com o domínio real (evitar `brevo-mail.com` a aparecer para o
   cliente).
5. Testar: enviar um lembrete de reserva real (ou usar
   `POST /operacoes/lavagem/lembretes/processar` manualmente), responder
   a partir de uma conta de email de teste, e confirmar que a resposta
   aparece em Conversations dentro de alguns minutos.
6. Definir quem monitoriza o inbox do Conversations (agente humano
   responsável por responder às dúvidas dos clientes).

## Webhook de contexto (implementado)

`app/presentation/api/v1/brevo_conversations.py` — quando uma conversa
começa no Conversations, o SIGES cruza o email do visitante com
`ContaClienteModel.email` e, se corresponder a um cliente do portal,
injecta automaticamente uma nota de contexto na conversa (nome do
cliente e a sua reserva mais recente: serviço, estado, data). O agente
humano vê isto assim que abre a conversa, sem ter de procurar
manualmente no SIGES.

Schema dos eventos da Brevo confirmado na documentação oficial
(`developers.brevo.com/docs/conversations-webhooks`) — o email do
visitante vem sempre em `visitor.attributes.EMAIL`, nunca num campo de
topo. A Brevo não assina os webhooks (sem HMAC) — a autenticidade é
garantida por um secret na própria URL do webhook.

### Configuração necessária

1. Variáveis de ambiente no `siges-backend` (Render ou `.env`):
   - `BREVO_API_KEY` — chave de API da conta Brevo (Settings → SMTP & API
     → API Keys), usada para chamar `POST /v3/conversations/{id}/messages`
     e injectar a nota de contexto.
   - `BREVO_CONVERSATIONS_WEBHOOK_SECRET` — um valor secreto à tua escolha
     (ex. gerar com `openssl rand -hex 16`), usado só para autenticar o
     webhook — não é fornecido pela Brevo.
2. Em Brevo → **Conversations** → **Settings** → **Integrations** →
   **Webhooks**, criar um webhook apontando para:
   ```
   https://<domínio-do-backend>/api/v1/brevo-conversations/webhook?secret=<BREVO_CONVERSATIONS_WEBHOOK_SECRET>
   ```
   (o mesmo valor definido em `BREVO_CONVERSATIONS_WEBHOOK_SECRET`).
3. Testar: um cliente com conta no portal inicia uma conversa (chat/email
   ligado) usando o mesmo email da sua conta — a nota de contexto deve
   aparecer na conversa dentro de segundos. Sem `BREVO_API_KEY`
   configurada, o webhook regista um aviso nos logs e não falha (apenas
   não envia a nota).

Se o email do visitante não corresponder a nenhuma `ContaClienteModel`
(visitante anónimo, ou cliente sem conta no portal), o webhook não faz
nada — não é tratado como erro.
