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

## Se no futuro se quiser ir mais além (trabalho de código, não feito agora)

Só faz sentido depois do passo acima estar validado em produção:

- Webhook FastAPI a receber eventos `Conversation Started` /
  `Conversation Fragment` da Brevo (configurável em Conversations →
  Settings → Integrations → Webhooks), para cruzar o email do contacto
  com o `cliente_id`/reserva no SIGES e mostrar contexto ao agente humano
  ao abrir a conversa. O payload do webhook não traz o ID da reserva —
  teria de se correlacionar pelo endereço de email do cliente.
- Isto é opcional e não bloqueia o objectivo actual (ligar as respostas a
  um humano), que se resolve inteiramente nos passos manuais acima.
