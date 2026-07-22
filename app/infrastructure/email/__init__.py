"""Envio de emails via SMTP (Outlook/Office365)."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
import asyncio
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _clean_email(raw: str) -> str:
    """Extrai apenas o endereço email de um valor possivelmente concatenado com comentários."""
    if not raw:
        return ""
    # Ficar apenas com o primeiro "token" (até ao primeiro espaço)
    return raw.strip().split()[0] if raw.strip() else ""


def _send_smtp_sync(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    """Envia email síncrono via SMTP. Devolve True/False."""
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP não configurado — email não enviado")
        return False

    from_email = _clean_email(settings.smtp_from_email) or _clean_email(settings.smtp_user)
    to_email = _clean_email(to)
    if not from_email or not to_email:
        logger.error(f"Endereços inválidos · from={from_email!r} to={to_email!r}")
        return False

    msg = EmailMessage()
    msg["From"] = formataddr((settings.smtp_from_name, from_email))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text or "Este email requer um cliente que suporte HTML.")
    msg.add_alternative(html, subtype="html")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
            s.ehlo()
            s.starttls(context=context)
            s.ehlo()
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        logger.info(f"Email enviado para {to} · assunto: {subject}")
        return True
    except Exception as e:
        logger.error(f"Erro a enviar email para {to}: {type(e).__name__}: {e}", exc_info=True)
        return False


async def send_email(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    """Wrapper async (corre o sync num executor para não bloquear)."""
    return await asyncio.get_event_loop().run_in_executor(
        None, _send_smtp_sync, to, subject, html, text
    )


def render_password_reset_email(*, user_name: str, reset_link: str, company_name: str = "Financ-BI Jennos") -> tuple[str, str]:
    """Devolve (html, text) do email de recuperação."""
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f7fb;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f7fb;padding:40px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb;">
        <tr><td style="background:#0b3b6f;padding:24px 32px;color:#ffffff;">
          <h1 style="margin:0;font-size:22px;font-weight:700;">{company_name}</h1>
          <p style="margin:4px 0 0;font-size:13px;opacity:0.85;">Recuperação de Senha</p>
        </td></tr>
        <tr><td style="padding:32px;">
          <p style="font-size:15px;color:#1a2332;margin:0 0 16px;">Olá <strong>{user_name}</strong>,</p>
          <p style="font-size:14px;color:#4a5568;line-height:1.6;margin:0 0 20px;">
            Recebemos um pedido para redefinir a senha da sua conta no <strong>{company_name}</strong>.
            Para continuar, clique no botão abaixo:
          </p>
          <table cellpadding="0" cellspacing="0" style="margin:24px auto;">
            <tr><td style="background:#1e5a9c;border-radius:6px;">
              <a href="{reset_link}" style="display:inline-block;padding:12px 28px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;">
                Redefinir senha
              </a>
            </td></tr>
          </table>
          <p style="font-size:13px;color:#6b7280;line-height:1.6;margin:0 0 8px;">
            Ou copie e cole este link no seu navegador:
          </p>
          <p style="font-size:12px;color:#4a5568;word-break:break-all;background:#f4f7fb;padding:10px;border-radius:4px;margin:0 0 20px;">
            {reset_link}
          </p>
          <p style="font-size:12px;color:#9ca3af;line-height:1.6;margin:20px 0 0;border-top:1px solid #e5e7eb;padding-top:16px;">
            ⏰ Este link expira em <strong>1 hora</strong>.<br>
            🔒 Se não fez este pedido, ignore este email. A sua senha não será alterada.
          </p>
        </td></tr>
        <tr><td style="background:#f9fafb;padding:16px 32px;border-top:1px solid #e5e7eb;text-align:center;">
          <p style="margin:0;font-size:11px;color:#9ca3af;">
            Este é um email automático. Não responda a esta mensagem.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text = f"""Recuperação de Senha · {company_name}

Olá {user_name},

Recebemos um pedido para redefinir a senha da sua conta.

Para continuar, abra o link abaixo no seu navegador:
{reset_link}

Este link expira em 1 hora.
Se não fez este pedido, ignore este email.
"""
    return html, text


__all__ = ["send_email", "render_password_reset_email"]
