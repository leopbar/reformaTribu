"""Importador da tabela oficial de CST e cClassTrib do IBS/CBS (Portal da Conformidade Fácil / SVRS).

Aceita:
- a página HTML "Classificação Tributária" do Portal DF-e da SVRS (os dados vêm embutidos na
  variável JavaScript `dadosOriginais`);
- um JSON com a mesma estrutura (lista de CSTs com `ClassificacoesTributarias`).

A tabela traz, para vários cClassTrib, a correlação oficial com códigos NCM/NBS dos anexos da
LC 214/2025 (itens permitidos e vedados), que alimenta a geração das regras declarativas.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Any

import orjson
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.core.codes import somente_digitos
from app.models import CClassTribCode, CClassTribCorrelacao, CstCode, RefVersion
from app.models.enums import FonteReferencia
from app.reference.importers.common import Coleta, FormatoInvalido, ativar_versao, criar_versao, parse_data_br

_VAR = re.compile(r"var\s+dadosOriginais\s*=\s*(\[.*?\]);\s*\n", re.S)

TIPO_ALIQUOTA = {1: "fixa", 2: "padrao", 3: "uniforme_setorial", 4: "sem_aliquota"}


def extrair_dados(dados: bytes) -> list[dict[str, Any]]:
    texto = dados.decode("utf-8", errors="replace")
    bruto = texto.strip()
    if bruto.startswith("["):
        try:
            lista = orjson.loads(bruto)
        except orjson.JSONDecodeError as e:
            raise FormatoInvalido("O arquivo JSON da tabela cClassTrib está corrompido.") from e
    else:
        m = _VAR.search(texto)
        if not m:
            raise FormatoInvalido(
                "Não encontrei os dados da tabela na página. Salve a página 'Classificação Tributária' do "
                "Portal da Conformidade Fácil (dfe-portal.svrs.rs.gov.br) ou envie o JSON correspondente."
            )
        lista = orjson.loads(m.group(1))
    if not isinstance(lista, list) or not lista or "ClassificacoesTributarias" not in lista[0]:
        raise FormatoInvalido("Estrutura inesperada: esperava uma lista de CSTs com 'ClassificacoesTributarias'.")
    return lista


def _dec(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _data(v: Any) -> Any:
    return parse_data_br(v[:10] if isinstance(v, str) else v)


def importar_cclasstrib(
    session: Session, coleta: Coleta, usuario_id: uuid.UUID | None = None, usuario_email: str | None = None
) -> tuple[RefVersion, bool]:
    lista = extrair_dados(coleta.dados)
    ext = "json" if coleta.dados.lstrip().startswith(b"[") else "html"
    publicacoes = sorted(
        {c.get("DthPublicacao", "")[:10] for cst in lista for c in cst.get("ClassificacoesTributarias") or []}
    )
    rotulo = f"Tabela cClassTrib (publicação mais recente {publicacoes[-1] if publicacoes else 'n/d'})"
    versao, criada = criar_versao(session, FonteReferencia.CCLASSTRIB, coleta, ext, rotulo, usuario_id, usuario_email)
    if not criada:
        return versao, False

    csts, codigos, correlacoes = [], [], []
    for cst in lista:
        indicadores_cst = {k: v for k, v in cst.items() if k.startswith("Ind")}
        csts.append(
            {
                "version_id": versao.id,
                "cst": cst["Cst"],
                "descricao": cst.get("NomeCst") or "",
                "indicadores": indicadores_cst,
                "data_inicio": _data(cst.get("DthIniVig")),
                "data_fim": _data(cst.get("DthFimVig")),
            }
        )
        for c in cst.get("ClassificacoesTributarias") or []:
            indicadores = {k: v for k, v in c.items() if k.startswith(("Ind", "Tipo", "Possui"))}
            codigos.append(
                {
                    "version_id": versao.id,
                    "codigo": c["CodClassTrib"],
                    "cst": c.get("Cst") or cst["Cst"],
                    "nome": c.get("NomeClassTrib") or "",
                    "nome_reduzido": c.get("NomeReduzido"),
                    "perc_red_ibs": _dec(c.get("PercRedIbs")),
                    "perc_red_cbs": _dec(c.get("PercRedCbs")),
                    "tipo_aliquota": TIPO_ALIQUOTA.get(c.get("TipoAliq") or 0, str(c.get("TipoAliq"))),
                    "nro_anexo": c.get("NroAnexo"),
                    "url_legislacao": c.get("TexUrlLegislacao"),
                    "texto_regulamento_cbs": c.get("TexRegCbs"),
                    "texto_regulamento_ibs": c.get("TexRegIbs"),
                    "ind_nfe": bool(c.get("IndNfe")),
                    "ind_nfce": bool(c.get("IndNfce")),
                    "ind_nfse": bool(c.get("IndNfse")),
                    "indicadores": indicadores,
                    "data_inicio": _data(c.get("DthIniVig")),
                    "data_fim": _data(c.get("DthFimVig")),
                }
            )
            for a in c.get("Anexos") or []:
                cod = somente_digitos(a.get("CodNcmNbs"))
                if not cod:
                    continue
                correlacoes.append(
                    {
                        "version_id": versao.id,
                        "cclasstrib": c["CodClassTrib"],
                        "nro_anexo": a.get("NroAnexo"),
                        "descricao_anexo": a.get("DescAnexo"),
                        "codigo_ncm_nbs": cod,
                        "tipo_codigo": (a.get("TipoCodigo") or ("NBS" if len(cod) == 9 else "NCM")).upper()[:3],
                        "tipo_permissao": a.get("TipoPermissao"),
                        "descricao_condicao": a.get("DescCondicao"),
                        "descricao_excecao": a.get("DescExcecao"),
                        "observacao": a.get("Observacao"),
                        "nro_item_anexo": str(a["NroItemAnexoLei"]) if a.get("NroItemAnexoLei") is not None else None,
                        "descricao_item_anexo": a.get("DescItemAnexo"),
                        "data_inicio": _data(a.get("DthIniVig")),
                        "data_fim": _data(a.get("DthFimVig")),
                    }
                )
    session.execute(insert(CstCode), csts)
    session.execute(insert(CClassTribCode), codigos)
    for i in range(0, len(correlacoes), 2000):
        session.execute(insert(CClassTribCorrelacao), correlacoes[i : i + 2000])
    ativar_versao(
        session,
        versao,
        {
            "csts": len(csts),
            "cclasstrib": len(codigos),
            "correlacoes": len(correlacoes),
            "publicacao_mais_recente": publicacoes[-1] if publicacoes else None,
        },
        [],
    )
    return versao, True
