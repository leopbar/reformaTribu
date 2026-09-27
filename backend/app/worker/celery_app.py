"""Aplicação Celery (filas: ingest, reference, pipeline, llm, export, default)."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.config import get_settings
from app.core.logging import configurar_logs

_s = get_settings()

celery_app = Celery("reforma", broker=_s.celery_broker_url, backend=None, include=["app.worker.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_serializer="json",
    accept_content=["json"],
    timezone="America/Sao_Paulo",
    enable_utc=True,
    broker_transport_options={"visibility_timeout": 3 * 3600},
    task_routes={
        "auditoria.preparar": {"queue": "ingest"},
        "auditoria.iniciar": {"queue": "pipeline"},
        "auditoria.processar_itens": {"queue": "pipeline"},
        "llm.coletar_lotes": {"queue": "llm"},
        "referencia.*": {"queue": "reference"},
        "exportacao.*": {"queue": "export"},
    },
    beat_schedule={
        "coletar-lotes": {"task": "llm.coletar_lotes", "schedule": float(_s.llm_batch_poll_s)},
        "recuperar-travados": {"task": "auditoria.recuperar_travados", "schedule": 300.0},
        "expurgar-arquivos": {"task": "manutencao.expurgar_arquivos", "schedule": crontab(hour=3, minute=15)},
        "verificar-fontes": {"task": "referencia.verificar_atualizacoes", "schedule": crontab(hour=4, minute=30)},
        "indexar-embeddings": {"task": "referencia.indexar_pendentes", "schedule": 600.0},
    },
)


@worker_process_init.connect
def _init(**_: object) -> None:
    configurar_logs(_s.log_level)
