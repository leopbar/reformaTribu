"""Checagem cruzada com os anexos da lei: produtos que a lei cita pelo nome.

Os anexos da LC 214 nomeiam produtos e dizem o código: "Água sanitária classificada no código
3808.94.19". Se a descrição do item traz esse nome e o NCM do item é outro, o NCM do ERP pode estar
errado — e com o código da lei o imposto muda (ex.: redução de 60%). O item vai para o contador com o
aviso, em vez de ser classificado com o código errado. Sem IA: comparação de texto com a base oficial.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.codes import formatar_codigo

# Onde termina o nome do produto no texto do item do anexo.
_CORTES = re.compile(
    r"\s(classificad|do codigo|dos codigos|da ncm|das subposic|da subposic|da posic|das posic|do capitulo|"
    r"dos capitulos|compreendid|exceto|relacionad|de que trata|constantes|codigos)|[,;:(]"
)


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t).split())


def nome_do_produto(texto_item: str) -> str:
    """O nome do produto no início do item do anexo ("Água sanitária classificada..." → "agua sanitaria")."""
    t = normalizar(texto_item)
    m = _CORTES.search(t)
    return (t[: m.start()] if m else t).strip()


@lru_cache(maxsize=4)
def _itens_do_anexo(version_id: str) -> tuple[tuple[str, str, str, tuple[str, ...]], ...]:
    """(anexo, item, nome do produto, códigos citados) de cada item de anexo da versão da lei."""
    from app.db.session import sync_engine

    with sync_engine().connect() as c:
        rows = c.execute(
            text(
                "SELECT anexo, item, texto, codigos_citados FROM legal_provisions "
                "WHERE version_id = :v AND tipo = 'anexo_item' AND cardinality(codigos_citados) > 0"
            ),
            {"v": uuid.UUID(version_id)},
        ).all()
    return tuple(
        (str(r.anexo or ""), str(r.item or ""), nome_do_produto(r.texto), tuple(r.codigos_citados or ())) for r in rows
    )


def _cita(descricao: str, nome: str) -> bool:
    """O nome da lei aparece na descrição? Nomes de 2+ palavras em qualquer posição; de 1 palavra, só
    como primeira palavra (evita "BISCOITO DE ARROZ" casar com "Arroz")."""
    palavras = nome.split()
    if not palavras or len(nome) < 4:
        return False
    if len(palavras) >= 2:
        return f" {nome} " in f" {descricao} "
    return descricao.split()[:1] == palavras


def codigos_da_lei_para_a_prova(
    versao_lei: str | None, descricao: str, codigo_atual: str | None
) -> list[dict[str, Any]]:
    """Itens de anexo que nomeiam o produto e cujos códigos devem entrar na prova do Identificador.

    Com código no cadastro, só os que citam OUTRO código (mesma regra do aviso ao contador). Sem código,
    os de nome com 2+ palavras (um nome de uma palavra, sem capítulo para comparar, é arriscado demais)."""
    if not versao_lei:
        return []
    if codigo_atual:
        return produtos_citados_com_outro_codigo(None, versao_lei, descricao, "ncm", codigo_atual)
    desc = normalizar(descricao)
    return [
        {"anexo": a, "item": i, "produto": nome, "codigos": [formatar_codigo("ncm", c) for c in codigos]}
        for a, i, nome, codigos in _itens_do_anexo(str(versao_lei))
        if len(nome.split()) >= 2 and _cita(desc, nome)
    ][:3]


def produtos_citados_com_outro_codigo(
    session: Session | None, versao_lei: str | None, descricao: str, tipo_codigo: str | None, codigo: str | None
) -> list[dict[str, Any]]:
    """Itens de anexo cujo produto aparece na descrição, mas que citam códigos que não abrangem o do item."""
    if not versao_lei or not codigo or tipo_codigo != "ncm":
        return []
    desc = normalizar(descricao)
    citados = [i for i in _itens_do_anexo(str(versao_lei)) if _cita(desc, i[2])]
    # A lei também nomeia este produto no próprio código do item (ex.: massas alimentícias em mais de um
    # anexo): o código tem tratamento na lei para esse produto, e o Jurista o estuda.
    if any(codigo.startswith(c) for _, _, _, codigos in citados for c in codigos):
        return []
    saida = []
    for anexo, item, nome, codigos in citados:
        # Nome de uma palavra ("ovos", "farinha") só vale no mesmo capítulo da NCM: "OVOS DE PÁSCOA" (cap. 18)
        # não é o "ovos" da lei (cap. 04). Nomes de 2+ palavras são específicos ("água sanitária").
        if len(nome.split()) == 1 and not any(codigo[:2] == c[:2] for c in codigos):
            continue
        saida.append(
            {
                "anexo": anexo,
                "item": item,
                "produto": nome,
                "codigos": [formatar_codigo("ncm", c) for c in codigos],
            }
        )
    return saida[:3]
