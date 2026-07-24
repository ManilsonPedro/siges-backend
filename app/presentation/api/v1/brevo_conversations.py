"""Webhook do Brevo Conversations — cruza o email do visitante com o
cliente/reserva no SIGES e injecta uma mensagem de contexto automática
na conversa, para o agente humano ver quem está a falar e o histórico
recente sem ter de procurar manualmente.

Ver LIGAR_BREVO_CONVERSATIONS.md para os passos de configuração da
conta (ligar a mailbox, criar o webhook em Conversations > Settings >
Integrations > Webhooks apontando para
POST /api/v1/brevo-conversations/webhook?secret=<BREVO_CONVERSATIONS_WEBHOOK_SECRET>).

Nota sobre segurança: a Brevo não assina os webhooks de Conversations
(sem HMAC) — a documentação oficial recomenda whitelisting de IP ou um
token na própria URL. Usamos um secret na query string por ser o único
mecanismo que não depende de saber os IPs de origem da Brevo.

Schema dos eventos (confirmado na documentação oficial, não adivinhado):
- conversationStarted: message (singular) + agent (singular) + visitor
- conversationFragment: messages (array) + agents (array) + visitor
- conversationTranscript: idêntico a fragment, + conversationStartPage
O email do visitante vem sempre em visitor.attributes.EMAIL (nunca num
campo de topo) — chave em maiúsculas, é um atributo de contacto Brevo.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.infrastructure.database import get_db
from app.infrastructure.database.models import (
    ClienteModel,
    ContaClienteModel,
    OrdemLavagemModel,
    SlotLavagemModel,
    TipoLavagemModel,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Schemas do payload da Brevo (verbatim da documentação) ──────────


class VisitorAttributes(BaseModel):
    EMAIL: Optional[str] = None

    class Config:
        extra = "allow"


class Visitor(BaseModel):
    id: Optional[str] = None
    threadId: Optional[str] = None
    contactId: Optional[int] = None
    attributes: Dict[str, Any] = {}
    integrationAttributes: Dict[str, Any] = {}

    class Config:
        extra = "allow"

    @property
    def email(self) -> Optional[str]:
        return (self.attributes or {}).get("EMAIL") or (self.integrationAttributes or {}).get("EMAIL")


class MessageStarted(BaseModel):
    id: Optional[str] = None
    type: Optional[str] = None
    text: Optional[str] = None

    class Config:
        extra = "allow"


class ConversationStartedEvent(BaseModel):
    eventName: Literal["conversationStarted"]
    conversationId: str
    message: Optional[MessageStarted] = None
    visitor: Visitor

    class Config:
        extra = "allow"


class ConversationFragmentEvent(BaseModel):
    eventName: Literal["conversationFragment"]
    conversationId: str
    messages: List[Dict[str, Any]] = []
    visitor: Visitor

    class Config:
        extra = "allow"


class ConversationTranscriptEvent(BaseModel):
    eventName: Literal["conversationTranscript"]
    conversationId: str
    messages: List[Dict[str, Any]] = []
    visitor: Visitor

    class Config:
        extra = "allow"


ConversationsWebhookEvent = Union[
    ConversationStartedEvent, ConversationFragmentEvent, ConversationTranscriptEvent
]


# ─── Cruzamento email → cliente/reserva ──────────────────────────────


async def _montar_contexto(db: AsyncSession, email: str) -> Optional[str]:
    """Devolve texto de contexto (cliente + reserva mais recente) para
    injectar na conversa, ou None se o email não corresponder a nenhuma
    conta de cliente do portal."""
    email_norm = email.strip().lower()
    cr = await db.execute(
        select(ContaClienteModel).where(ContaClienteModel.email == email_norm)
    )
    conta = cr.scalar_one_or_none()
    if not conta:
        return None

    linhas = []

    clr = await db.execute(select(ClienteModel).where(ClienteModel.id == UUID(conta.cliente_id)))
    cliente = clr.scalar_one_or_none()
    linhas.append(f"Cliente SIGES: {cliente.nome if cliente else '—'} ({email_norm})")

    r = await db.execute(
        select(OrdemLavagemModel)
        .where(OrdemLavagemModel.cliente_id == conta.cliente_id)
        .order_by(OrdemLavagemModel.created_at.desc())
        .limit(1)
    )
    ordem = r.scalar_one_or_none()
    if not ordem:
        linhas.append("Sem reservas registadas no portal.")
        return "\n".join(linhas)

    tr = await db.execute(select(TipoLavagemModel).where(TipoLavagemModel.id == ordem.tipo_lavagem_id))
    tipo = tr.scalar_one_or_none()

    slot_info = ""
    if ordem.slot_id:
        sr = await db.execute(select(SlotLavagemModel).where(SlotLavagemModel.id == ordem.slot_id))
        slot = sr.scalar_one_or_none()
        if slot:
            slot_info = f" · agendada para {slot.data_hora_inicio.strftime('%d/%m/%Y %H:%M')}"

    linhas.append(
        f"Última reserva: {tipo.nome if tipo else 'lavagem'} — estado \"{ordem.estado}\"{slot_info} "
        f"(origem: {ordem.origem}, criada em {ordem.created_at.strftime('%d/%m/%Y %H:%M')})"
    )
    return "\n".join(linhas)


async def _enviar_mensagem_agente(conversation_id: str, texto: str) -> None:
    """Injecta uma mensagem automática (visível só à equipa, como nota
    de contexto) na conversa via API do Conversations."""
    if not settings.brevo_api_key:
        logger.warning("brevo_conversations: BREVO_API_KEY não configurada — contexto não enviado")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.brevo.com/v3/conversations/{conversation_id}/messages",
                headers={"api-key": settings.brevo_api_key, "Content-Type": "application/json"},
                json={"text": texto, "type": "note"},
            )
            if resp.status_code >= 400:
                logger.warning(
                    "brevo_conversations: falha ao enviar contexto (status=%s, body=%s)",
                    resp.status_code, resp.text[:300],
                )
    except Exception:
        logger.exception("brevo_conversations: erro ao chamar a API de Conversations")


# ─── Endpoint ─────────────────────────────────────────────────────────


@router.post("/webhook")
async def brevo_conversations_webhook(
    req: Request,
    secret: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Recebe eventos conversationStarted/Fragment/Transcript da Brevo.
    Sem assinatura HMAC disponível (não documentada pela Brevo) — a
    autenticidade é garantida por um secret na query string, conhecido
    apenas por nós e configurado na própria URL do webhook na Brevo."""
    if settings.brevo_conversations_webhook_secret:
        if secret != settings.brevo_conversations_webhook_secret:
            raise HTTPException(401, "Secret inválido")

    body = await req.json()
    event_name = body.get("eventName")
    if event_name not in ("conversationStarted", "conversationFragment", "conversationTranscript"):
        # Evento desconhecido/futuro — não é erro nosso, apenas ignoramos.
        return {"status": "ignored", "reason": "eventName desconhecido"}

    visitor = body.get("visitor") or {}
    email = (visitor.get("attributes") or {}).get("EMAIL") or (visitor.get("integrationAttributes") or {}).get("EMAIL")
    conversation_id = body.get("conversationId")

    if not email or not conversation_id:
        return {"status": "skipped", "reason": "sem email de visitante ou conversationId"}

    # Só injectamos contexto uma vez por conversa — ao seu início — para
    # não poluir a conversa com a mesma nota em cada fragmento/mensagem.
    if event_name != "conversationStarted":
        return {"status": "skipped", "reason": f"contexto já enviado no início da conversa ({event_name} ignorado)"}

    contexto = await _montar_contexto(db, email)
    if not contexto:
        return {"status": "skipped", "reason": "email não corresponde a nenhuma conta de cliente do SIGES"}

    await _enviar_mensagem_agente(conversation_id, contexto)
    return {"status": "ok", "conversation_id": conversation_id}


__all__ = ["router"]
