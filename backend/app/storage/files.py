"""Armazenamento de arquivos (volume local). Caminhos relativos ficam gravados no banco."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from pathlib import Path

from app.config import get_settings


def raiz() -> Path:
    r = get_settings().storage_dir
    r.mkdir(parents=True, exist_ok=True)
    return r


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def salvar(area: str, dados: bytes, extensao: str) -> str:
    """Grava e devolve o caminho relativo. `area` ex.: 'uploads/<org_id>' ou 'referencia/ncm'."""
    ext = extensao.lower().lstrip(".")
    rel = Path(area) / date.today().strftime("%Y/%m") / f"{uuid.uuid4().hex}.{ext}"
    destino = raiz() / rel
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(dados)
    return rel.as_posix()


def caminho(rel: str) -> Path:
    p = (raiz() / rel).resolve()
    if raiz().resolve() not in p.parents:
        raise ValueError("Caminho de arquivo inválido.")
    return p


def ler(rel: str) -> bytes:
    return caminho(rel).read_bytes()


def apagar(rel: str) -> None:
    p = caminho(rel)
    if p.exists():
        p.unlink()
