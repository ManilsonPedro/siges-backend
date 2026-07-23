"""Scheduler in-process (APScheduler) para tarefas periódicas simples que
antes dependiam de um cron externo (ex. lembretes de reserva de lavagem,
Sprint 6). Roda dentro do mesmo processo da app FastAPI — sem worker/broker
separado, adequado à escala actual do SIGES.

Uso: chamar `iniciar_scheduler()` no startup do app (app/main.py) e
`parar_scheduler()` no shutdown.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _job_lembretes_reserva() -> None:
    from app.infrastructure.database import AsyncSessionLocal
    from app.presentation.api.v1.operacoes_lavagem import processar_lembretes_reserva

    async with AsyncSessionLocal() as db:
        try:
            enviados = await processar_lembretes_reserva(db)
            if enviados:
                logger.info("scheduler: %d lembrete(s) de reserva enviado(s)", enviados)
        except Exception:
            logger.exception("scheduler: falha ao processar lembretes de reserva")


def iniciar_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _job_lembretes_reserva,
        "interval",
        minutes=5,
        id="lembretes_reserva_lavagem",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("scheduler in-process iniciado (lembretes_reserva_lavagem a cada 5min)")


def parar_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


__all__ = ["iniciar_scheduler", "parar_scheduler"]
