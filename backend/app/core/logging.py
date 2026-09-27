"""Logs estruturados em JSON com identificador de correlação.

Nunca registre dados pessoais, descrições de itens de clientes, senhas ou chaves.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSIVEL = re.compile(r"(senha|password|token|secret|api[_-]?key|authorization|cookie)", re.I)


def _mascarar(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for k in list(event_dict):
        if _SENSIVEL.search(k):
            event_dict[k] = "***"
    return event_dict


def configurar_logs(nivel: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=nivel.upper())
    for ruidoso in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _mascarar,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(nivel.upper())),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
