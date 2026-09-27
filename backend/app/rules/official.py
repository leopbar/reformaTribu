"""Geração das regras declarativas a partir das fontes oficiais importadas.

Fontes, em ordem de preferência:
1. Correlação oficial cClassTrib ↔ NCM/NBS publicada com a tabela cClassTrib (itens permitidos e
   vedados de cada anexo).
2. Texto dos anexos da LC 214/2025, para anexos sem correlação oficial (códigos citados no texto).
3. Anexo XVII (Imposto Seletivo), extraído do texto da lei.
4. Regra padrão de tributação integral (cClassTrib da tabela oficial).

Toda regra gerada nasce com status `pendente_revisao` e só passa a valer depois de aprovada por
um superadministrador. Nenhum conteúdo é inventado: códigos, descrições, CST e cClassTrib vêm
exclusivamente das tabelas e do texto importados.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.codes import somente_digitos
from app.models import CClassTribCode, CClassTribCorrelacao, LegalProvision, LegalRule, RefVersion, RuleCode
from app.models.enums import FonteReferencia, OrigemRegra, StatusRegra, TipoTratamento
from app.reference.importers.common import versao_ativa
from app.reference.importers.lc214 import ROMANOS
from app.rules.schema import nivel_por_tamanho

PALAVRAS_CONDICAO = (
    "sem adição",
    "sem adicao",
    "exceto",
    "destinad",
    "quando ",
    "desde que",
    "uso veterin",
    "in natura",
    "ressalvad",
    "não se aplica",
    "nao se aplica",
    "com adição",
    "integral",
)


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", t)).strip()


def _sha8(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()[:8]


def romano(n: int | None) -> str | None:
    return ROMANOS[n - 1] if n and 1 <= n <= len(ROMANOS) else None


def tratamento_por_cclasstrib(c: CClassTribCode) -> str:
    red = float(c.perc_red_cbs or c.perc_red_ibs or 0)
    if c.cst == "000":
        return TipoTratamento.TRIBUTACAO_INTEGRAL
    if c.cst == "400":
        return TipoTratamento.ISENCAO
    if c.cst == "410":
        return TipoTratamento.IMUNIDADE
    if c.cst in ("200", "011", "515"):
        if red >= 100:
            return TipoTratamento.ALIQUOTA_ZERO
        if abs(red - 60) < 0.01:
            return TipoTratamento.REDUCAO_60
        if abs(red - 30) < 0.01:
            return TipoTratamento.REDUCAO_30
        if abs(red - 40) < 0.01:
            return TipoTratamento.REDUCAO_40
        return TipoTratamento.REDUCAO_OUTRA
    return TipoTratamento.REGIME_ESPECIFICO


def tratamento_por_titulo(titulo: str) -> str:
    t = _norm(titulo)
    if "imposto seletivo" in t:
        return TipoTratamento.IMPOSTO_SELETIVO
    if "reducao a zero" in t or "100" in t:
        return TipoTratamento.ALIQUOTA_ZERO
    if "60" in t:
        return TipoTratamento.REDUCAO_60
    if "30" in t:
        return TipoTratamento.REDUCAO_30
    return TipoTratamento.REDUCAO_OUTRA


def artigo_da_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"#art(\d+)([a-z]?)", url, re.I)
    if not m:
        return None
    return f"art. {m.group(1)}" + (f"-{m.group(2).upper()}" if m.group(2) else "")


@dataclass
class RegraGerada:
    slug: str
    anexo: str | None
    item: str | None
    titulo_anexo: str | None
    descricao_legal: str
    dispositivo_legal: str
    tipo_tratamento: str
    tipo_codigo: str | None
    abrangencia: dict[str, Any]
    excecoes: list[dict[str, Any]]
    cst: str | None
    cclasstrib: str | None
    origem: str
    provision_id: Any = None
    fonte_version_id: Any = None
    avisos: list[dict[str, str]] = field(default_factory=list)
    prioridade: int = 100

    def assinatura(self) -> str:
        chave = {
            "abr": self.abrangencia,
            "exc": self.excecoes,
            "cst": self.cst,
            "cct": self.cclasstrib,
            "desc": self.descricao_legal,
            "trat": self.tipo_tratamento,
            "disp": self.dispositivo_legal,
        }
        if self.tipo_codigo == "nbs":
            # Só para NBS: incluir sempre mudaria a assinatura (e criaria versões novas) de todas as regras NCM.
            chave["tipo"] = self.tipo_codigo
        return hashlib.sha256(repr(sorted(chave.items(), key=lambda kv: kv[0])).encode()).hexdigest()


def _avisos_texto(texto: str) -> list[dict[str, str]]:
    t = texto.lower()
    if any(p in t for p in PALAVRAS_CONDICAO):
        return [
            {
                "codigo": "CONDICOES_TEXTUAIS",
                "mensagem": "O texto legal traz condições ou exceções descritas em palavras. Estruture-as "
                "(manualmente ou com 'Sugerir condições com IA') antes de aprovar a regra.",
            }
        ]
    return []


def _melhor_dispositivo(provisoes: list[LegalProvision], texto: str) -> LegalProvision | None:
    alvo = _norm(texto)[:400]
    melhor, nota = None, 0.0
    for p in provisoes:
        r = difflib.SequenceMatcher(None, alvo, _norm(p.texto.split("\nCódigos:")[0])[:400]).ratio()
        if r > nota:
            melhor, nota = p, r
    return melhor if nota >= 0.55 else None


def gerar_regras(session: Session) -> list[RegraGerada]:
    v_cct = versao_ativa(session, FonteReferencia.CCLASSTRIB)
    v_lc = versao_ativa(session, FonteReferencia.LC214)
    if v_cct is None:
        raise ValueError("Importe a tabela cClassTrib antes de gerar as regras.")
    cclass = {c.codigo: c for c in session.scalars(select(CClassTribCode).where(CClassTribCode.version_id == v_cct.id))}
    provisoes: dict[str, list[LegalProvision]] = defaultdict(list)
    if v_lc is not None:
        for p in session.scalars(
            select(LegalProvision)
            .where(LegalProvision.version_id == v_lc.id, LegalProvision.tipo == "anexo_item")
            .order_by(LegalProvision.ordem)
        ):
            provisoes[p.anexo or ""].append(p)

    regras: list[RegraGerada] = []

    # 1) Correlação oficial
    grupos: dict[tuple[str, int | None, str], list[CClassTribCorrelacao]] = defaultdict(list)
    for c in session.scalars(select(CClassTribCorrelacao).where(CClassTribCorrelacao.version_id == v_cct.id)):
        grupos[(c.cclasstrib, c.nro_anexo, c.descricao_item_anexo or c.descricao_anexo or "")].append(c)
    anexos_com_correlacao: set[str] = set()
    for (cod_cct, nro_anexo, descricao), linhas in sorted(grupos.items(), key=lambda kv: (kv[0][0], kv[0][2])):
        cct = cclass.get(cod_cct)
        if cct is None:
            continue
        tipo_codigo = "nbs" if linhas[0].tipo_codigo.upper() == "NBS" else "ncm"
        permitidos = sorted({x.codigo_ncm_nbs for x in linhas if (x.tipo_permissao or "PERMITIDO") != "VEDADO"})
        vedados = sorted({x.codigo_ncm_nbs for x in linhas if x.tipo_permissao == "VEDADO"})
        if not permitidos:
            continue
        anexo_r = romano(nro_anexo) if nro_anexo and nro_anexo <= 23 else None
        if anexo_r:
            anexos_com_correlacao.add(anexo_r)
        prov = _melhor_dispositivo(provisoes.get(anexo_r or "", []), descricao) if anexo_r else None
        artigo = artigo_da_url(cct.url_legislacao)
        partes = ["LC 214/2025"]
        if artigo:
            partes.append(artigo)
        if anexo_r:
            partes.append(f"Anexo {anexo_r}")
        if prov and prov.item:
            partes.append(f"item {prov.item}")
        excecao_textual = next((x.descricao_excecao for x in linhas if x.descricao_excecao), None)
        titulo = next((x.descricao_condicao for x in linhas if x.descricao_condicao), None) or linhas[0].descricao_anexo
        # Identificador estável: não depende de a LC já ter sido importada (o item do anexo pode
        # ser associado depois sem gerar uma regra duplicada).
        slug = f"cct-{cod_cct}-{_sha8(_norm(descricao))}"
        excecoes: list[dict[str, Any]] = [{"codigo": v, "nivel": nivel_por_tamanho(tipo_codigo, v)} for v in vedados]
        if excecao_textual:
            excecoes.append({"descricao": excecao_textual, "trecho_legal": excecao_textual})
        texto_legal = descricao or cct.nome
        regras.append(
            RegraGerada(
                slug=slug,
                anexo=anexo_r,
                item=prov.item if prov else None,
                titulo_anexo=titulo,
                descricao_legal=texto_legal,
                dispositivo_legal=", ".join(partes),
                tipo_tratamento=tratamento_por_cclasstrib(cct),
                tipo_codigo=tipo_codigo,
                abrangencia={
                    "universal": False,
                    "codigos": [{"codigo": c, "nivel": nivel_por_tamanho(tipo_codigo, c)} for c in permitidos],
                },
                excecoes=excecoes,
                cst=cct.cst,
                cclasstrib=cct.codigo,
                origem=OrigemRegra.CORRELACAO_OFICIAL,
                provision_id=prov.id if prov else None,
                fonte_version_id=v_cct.id,
                avisos=_avisos_texto(texto_legal + " " + (excecao_textual or "")),
            )
        )

    # 2) Anexos da lei sem correlação oficial (somente anexos de benefício: título "SUBMETID...")
    for anexo_r, provs in provisoes.items():
        if not anexo_r or anexo_r in anexos_com_correlacao or anexo_r == "XVII":
            continue
        titulo = provs[0].titulo_anexo or ""
        if "SUBMETID" not in titulo.upper():
            continue
        numero = ROMANOS.index(anexo_r) + 1
        ccts = [c for c in cclass.values() if c.nro_anexo == numero]
        cct = ccts[0] if len(ccts) == 1 else None
        for p in provs:
            codigos = [c for c in p.codigos_citados if c]
            if not codigos:
                continue
            # NBS é citada como "1.2204" ou "1.2201.1" (um dígito, ponto, quatro dígitos).
            tipo_codigo = "nbs" if re.search(r"(?<![\d.])\d\.\d{4}", p.texto) else "ncm"
            avisos = [
                {
                    "codigo": "GERADA_DO_TEXTO_LEGAL",
                    "mensagem": "Não há correlação oficial publicada para este anexo; os códigos foram lidos do "
                    "texto da lei. Confira códigos e níveis antes de aprovar.",
                },
                *_avisos_texto(p.texto),
            ]
            if cct is None:
                avisos.append(
                    {
                        "codigo": "CCLASSTRIB_INDEFINIDO",
                        "mensagem": f"A tabela oficial tem {len(ccts)} cClassTrib associados ao Anexo {anexo_r}; "
                        "defina o CST e o cClassTrib corretos antes de aprovar.",
                    }
                )
            regras.append(
                RegraGerada(
                    slug=f"anexo-{anexo_r.lower()}-item-{p.item}",
                    anexo=anexo_r,
                    item=p.item,
                    titulo_anexo=titulo,
                    descricao_legal=p.texto.split("\nCódigos:")[0],
                    dispositivo_legal=", ".join(
                        x
                        for x in (
                            "LC 214/2025",
                            artigo_da_url(cct.url_legislacao if cct else None),
                            f"Anexo {anexo_r}",
                            f"item {p.item}",
                        )
                        if x
                    ),
                    tipo_tratamento=tratamento_por_cclasstrib(cct) if cct else tratamento_por_titulo(titulo),
                    tipo_codigo=tipo_codigo,
                    abrangencia={
                        "universal": False,
                        "codigos": [{"codigo": c, "nivel": nivel_por_tamanho(tipo_codigo, c)} for c in codigos],
                    },
                    excecoes=[],
                    cst=cct.cst if cct else None,
                    cclasstrib=cct.codigo if cct else None,
                    origem="texto_legal",
                    provision_id=p.id,
                    fonte_version_id=v_lc.id if v_lc else None,
                    avisos=avisos,
                )
            )

    # 3) Imposto Seletivo (Anexo XVII). O artigo é o que remete ao Anexo XVII no texto da lei.
    art_is = None
    if v_lc is not None:
        art_is = session.scalar(
            select(LegalProvision.artigo)
            .where(
                LegalProvision.version_id == v_lc.id,
                LegalProvision.tipo == "artigo",
                LegalProvision.texto.ilike("%Anexo XVII%"),
            )
            .order_by(LegalProvision.ordem)
            .limit(1)
        )
    for p in provisoes.get("XVII", []):
        if not p.codigos_citados:
            continue
        texto_cod = p.texto.split("\nCódigos:")[-1] if "\nCódigos:" in p.texto else ""
        vedados_is = {somente_digitos(m) for m in re.findall(r"exceto o c[óo]digo\s+([\d.]+)", texto_cod, re.I)}
        excecoes_is: list[dict[str, Any]] = [
            {"codigo": v, "nivel": nivel_por_tamanho("ncm", v)} for v in sorted(vedados_is)
        ]
        for m in re.findall(r"\(exceto ([^)]+)\)", texto_cod, re.I):
            if {"descricao": f"exceto {m}"} not in [{"descricao": e.get("descricao")} for e in excecoes_is]:
                excecoes_is.append({"descricao": f"exceto {m}", "trecho_legal": f"(exceto {m})"})
        for m in re.findall(r"ressalvad[oa]s ([^;]+)", texto_cod, re.I):
            excecoes_is.append({"descricao": f"ressalvados {m.strip()}", "trecho_legal": m.strip()})
        codigos = [c for c in p.codigos_citados if c not in vedados_is]
        regras.append(
            RegraGerada(
                slug=f"anexo-xvii-item-{p.item}",
                anexo="XVII",
                item=p.item,
                titulo_anexo=p.titulo_anexo,
                descricao_legal=p.texto.replace("\nCódigos:", " —"),
                dispositivo_legal=(
                    f"LC 214/2025, {'art. ' + art_is + ', ' if art_is else ''}Anexo XVII, "
                    f"item {p.item} ({p.texto.split(chr(10))[0]})"
                ),
                tipo_tratamento=TipoTratamento.IMPOSTO_SELETIVO,
                tipo_codigo="ncm",
                abrangencia={
                    "universal": False,
                    "codigos": [{"codigo": c, "nivel": nivel_por_tamanho("ncm", c)} for c in codigos],
                },
                excecoes=excecoes_is,
                cst=None,
                cclasstrib=None,
                origem="texto_legal",
                provision_id=p.id,
                fonte_version_id=v_lc.id if v_lc else None,
                avisos=_avisos_texto(p.texto),
                prioridade=10,
            )
        )

    # 4) Regra padrão (tributação integral), só se o cClassTrib existir na tabela oficial
    padrao = next((c for c in cclass.values() if c.cst == "000" and c.codigo.endswith("001")), None)
    if padrao is not None:
        regras.append(
            RegraGerada(
                slug="padrao-tributacao-integral",
                anexo=None,
                item=None,
                titulo_anexo=None,
                descricao_legal=padrao.nome,
                dispositivo_legal="LC 214/2025, " + (artigo_da_url(padrao.url_legislacao) or "regra geral"),
                tipo_tratamento=TipoTratamento.TRIBUTACAO_INTEGRAL,
                tipo_codigo=None,
                abrangencia={"universal": True, "codigos": []},
                excecoes=[],
                cst=padrao.cst,
                cclasstrib=padrao.codigo,
                origem=OrigemRegra.CORRELACAO_OFICIAL,
                fonte_version_id=v_cct.id,
                prioridade=1000,
                avisos=[
                    {
                        "codigo": "REGRA_PADRAO",
                        "mensagem": "Aplicada somente quando nenhuma regra de anexo casa com o código do item.",
                    }
                ],
            )
        )
    return regras


def sincronizar_codigos(session: Session, regra: LegalRule) -> None:
    session.execute(delete(RuleCode).where(RuleCode.rule_id == regra.id))
    if not regra.tipo_codigo:
        return
    linhas = [
        RuleCode(rule_id=regra.id, tipo_codigo=regra.tipo_codigo, prefixo=c["codigo"], excecao=False)
        for c in (regra.abrangencia or {}).get("codigos", [])
    ] + [
        RuleCode(rule_id=regra.id, tipo_codigo=regra.tipo_codigo, prefixo=e["codigo"], excecao=True)
        for e in regra.excecoes or []
        if e.get("codigo")
    ]
    session.add_all(linhas)


def aplicar_regras_geradas(session: Session, geradas: list[RegraGerada]) -> dict[str, int]:
    """Cria versões novas (pendentes) para regras novas ou alteradas. Nunca sobrescreve."""
    from app.rules.validation import validar_regra

    ultimas: dict[str, LegalRule] = {}
    for r in session.scalars(select(LegalRule).order_by(LegalRule.slug, LegalRule.versao)):
        ultimas[r.slug] = r
    contagem = {"novas": 0, "alteradas": 0, "inalteradas": 0}
    for g in geradas:
        atual = ultimas.get(g.slug)
        if atual is not None and atual.extracao.get("assinatura") == g.assinatura():
            contagem["inalteradas"] += 1
            continue
        regra = LegalRule(
            slug=g.slug,
            versao=(atual.versao + 1) if atual else 1,
            anexo=g.anexo,
            item=g.item,
            titulo_anexo=g.titulo_anexo,
            descricao_legal=g.descricao_legal,
            dispositivo_legal=g.dispositivo_legal,
            tipo_tratamento=g.tipo_tratamento,
            tipo_codigo=g.tipo_codigo,
            abrangencia=g.abrangencia,
            excecoes=g.excecoes,
            condicoes=list(atual.condicoes) if atual else [],
            cst_ibs_cbs=g.cst,
            cclasstrib=g.cclasstrib,
            status=StatusRegra.PENDENTE_REVISAO,
            origem=g.origem,
            fonte_version_id=g.fonte_version_id,
            provision_id=g.provision_id,
            prioridade=g.prioridade,
            avisos=g.avisos
            + (
                [{"codigo": "CONDICOES_COPIADAS", "mensagem": f"Condições copiadas da versão {atual.versao}."}]
                if atual and atual.condicoes
                else []
            ),
            extracao={"assinatura": g.assinatura(), "gerada_por": "fontes_oficiais"},
            substitui_id=atual.id if atual else None,
        )
        if atual is not None and atual.status in (StatusRegra.PENDENTE_REVISAO, StatusRegra.INVALIDA):
            # Só uma versão pendente por regra; a aprovada (se houver) continua valendo até a nova ser aprovada.
            atual.status = StatusRegra.SUBSTITUIDA
        session.add(regra)
        session.flush()
        sincronizar_codigos(session, regra)
        validar_regra(session, regra, divergencias=False)
        contagem["alteradas" if atual else "novas"] += 1

    # Regras geradas automaticamente que deixaram de existir nas fontes oficiais.
    geradas_slugs = {g.slug for g in geradas}
    contagem["retiradas"] = 0
    for slug, r in ultimas.items():
        if slug in geradas_slugs or r.origem not in (OrigemRegra.CORRELACAO_OFICIAL, OrigemRegra.TEXTO_LEGAL):
            continue
        if r.status in (StatusRegra.PENDENTE_REVISAO, StatusRegra.INVALIDA):
            r.status = StatusRegra.SUBSTITUIDA
            contagem["retiradas"] += 1
        elif r.status == StatusRegra.APROVADA and not any(a.get("codigo") == "FONTE_REMOVIDA" for a in r.avisos or []):
            r.avisos = [
                *(r.avisos or []),
                {
                    "codigo": "FONTE_REMOVIDA",
                    "mensagem": "Esta regra não aparece mais nas fontes oficiais vigentes. "
                    "Revise se deve ser rejeitada.",
                },
            ]
    return contagem


def versoes_fonte(session: Session) -> dict[str, RefVersion | None]:
    return {f.value: versao_ativa(session, f.value) for f in FonteReferencia}
