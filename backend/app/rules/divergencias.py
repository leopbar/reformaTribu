"""Detecção de divergências entre a regra estruturada, o texto da LC 214/2025 e a tabela oficial.

A correlação oficial cClassTrib ↔ NCM/NBS e o texto da lei nem sempre dizem a mesma coisa (ex.: a
lei exclui "salmonídeos… classificados na subposição 0304.4", e a tabela veta a subposição
inteira). Aqui o texto do item do anexo é lido em partes (incluídos, exceções por código,
exceções parciais e restrições em palavras) e comparado com a regra no nível dos códigos folha
da nomenclatura vigente. Nada é corrigido automaticamente: cada divergência vira um aviso com os
códigos envolvidos e uma ação sugerida, e a aprovação passa a exigir justificativa do revisor.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CClassTribCode, LegalProvision, LegalRule, NbsNode, NcmNode
from app.models.enums import FonteReferencia, StatusRegra, TipoTratamento
from app.reference.importers.common import versao_ativa
from app.reference.importers.lc214 import ROMANOS, extrair_codigos

MAX_CODIGOS_AVISO = 300

_ALINEA = re.compile(r"(?:^|(?<=[\s:;,]))[a-z]\)\s")
_EXCETO = re.compile(r"\b(exceto|excetuad[oa]s?|excluíd[oa]s?|ressalvad[oa]s?)\b", re.I)
_ANEXOS_REF = re.compile(
    r"(?:(?:os\s+)?produtos\s+)?(?:relacionad|constante|previst|listad|referid)\w*\s+n[oa]s?\s+"
    r"Anexos?\s+([IVXL]+(?:\s*(?:,|e)\s*[IVXL]+)*)\b",
    re.I,
)
_PARENTESES = re.compile(r"\(([^()]*)\)")
_CAPITULOS = re.compile(r"Cap[íi]tulos\s+(\d{1,2}(?:\s*(?:,|e)\s*\d{1,2})*)", re.I)
# "exceto os produtos das subposições e dos códigos 0302.1…": exceção pelo código inteiro.
_EXCECAO_TOTAL = re.compile(
    r"^(?:(?:os|as|o|a)\s+)?(?:produtos\s+)?(?:classificad[oa]s\s+)?(?:(?:d|n)[aoe]s?\s+)?"
    r"(?:(?:subposi\w*|c[óo]digos?|posi\w*|itens?|cap[íi]tulos?|NCM(?:/SH)?|NBS)\s*(?:,|e)?\s*(?:(?:d|n)[aoe]s?\s+)?)+$",
    re.I,
)
_RESTRICOES = re.compile(
    r"\b(desde que|sem adi[çc][ãa]o|com adi[çc][ãa]o|destinad[oa]s?|de uso veterin|quando|in natura|"
    r"n[ãa]o se aplica)\b[^;.)]{0,160}",
    re.I,
)

ACOES = {
    "incluir_na_abrangencia": "Incluir no benefício",
    "remover_da_abrangencia": "Retirar do benefício",
    "adicionar_excecao": "Adicionar como exceção",
}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def _radical(palavra: str) -> str:
    p = _norm(palavra)
    for suf in ("oes", "aes", "ns", "es", "s"):
        if len(p) > 4 and p.endswith(suf):
            return p[: -len(suf)] + ("m" if suf == "ns" else "")
    return p


# ------------------------------------------------------------------ leitura do texto legal --
@dataclass
class ExcecaoParcial:
    descritor: str
    termos: list[str]
    codigos: list[str]


@dataclass
class LeituraLei:
    incluidos: list[str] = field(default_factory=list)
    excluidos: list[str] = field(default_factory=list)
    parciais: list[ExcecaoParcial] = field(default_factory=list)
    restricoes: list[str] = field(default_factory=list)
    anexos_excluidos: list[str] = field(default_factory=list)

    @property
    def todos_codigos(self) -> list[str]:
        return [*self.incluidos, *self.excluidos, *(c for p in self.parciais for c in p.codigos)]


def _codigos(trecho: str, coluna: bool) -> list[str]:
    caps: list[str] = []
    for m in _CAPITULOS.finditer(trecho):
        caps += [n.zfill(2) for n in re.findall(r"\d{1,2}", m.group(1))]
    return list(dict.fromkeys([*caps, *extrair_codigos(_CAPITULOS.sub(" ", trecho), coluna_codigos=coluna)]))


def _termos(descritor: str) -> list[str]:
    base = re.split(
        r"\b(?:classificad|compreendid|inclu[íi]d|d[aoe]s? (?:subposi|c[óo]dig|posi))", descritor, flags=re.I
    )[0]
    partes = re.split(r",|\be\b|\bou\b", base)
    termos = []
    for p in partes:
        p = re.sub(r"^\s*(?:os|as|o|a|de|do|da|dos|das)\s+", "", p.strip(), flags=re.I)
        if len(_norm(p)) >= 3:
            termos.append(" ".join(_radical(w) for w in p.split()))
    return termos


def _ler_fragmento(frag: str, coluna: bool, saida: LeituraLei) -> None:
    # split com grupo de captura: [antes, palavra1, cláusula1, palavra2, cláusula2, …]
    partes = _EXCETO.split(frag)
    saida.incluidos += _codigos(partes[0], coluna)
    for palavra, clausula in zip(partes[1::2], partes[2::2], strict=True):
        # "ressalvados os produtos relacionados nos Anexos I e XV": exclusão por referência a outro anexo.
        for m in _ANEXOS_REF.finditer(clausula):
            saida.anexos_excluidos += re.findall(r"[IVXL]+", m.group(1))
        resto = _ANEXOS_REF.sub(" ", clausula)
        cods = _codigos(resto, coluna)
        if not cods:
            texto = re.sub(r"\s+", " ", resto).strip(" ;,.")
            if not re.fullmatch(r"(?:e|os|as|o|a|produtos|\s)*", _norm(texto)):
                saida.restricoes.append(f"{palavra} {texto}")
            continue
        pos = re.search(r"\d|Cap[íi]tulo", resto)
        prefixo = re.sub(r"\s+", " ", resto[: pos.start()] if pos else resto).strip(" ,;")
        if not prefixo or _EXCECAO_TOTAL.match(prefixo):
            saida.excluidos += cods
        else:
            saida.parciais.append(ExcecaoParcial(descritor=prefixo, termos=_termos(prefixo), codigos=cods))


def ler_texto_legal(texto: str) -> LeituraLei:
    """Lê um item de anexo: "descrição\\nCódigos: …" (coluna de códigos) ou descrição com códigos."""
    saida = LeituraLei()
    descricao, _, coluna = (texto or "").partition("\nCódigos:")

    def restricoes_entre_parenteses(t: str) -> str:
        def sub(m: re.Match[str]) -> str:
            dentro = m.group(1)
            if not re.search(r"\d", dentro) and (_EXCETO.search(dentro) or _RESTRICOES.search(dentro)):
                saida.restricoes.append(dentro.strip())
                return " "
            return m.group(0)

        return _PARENTESES.sub(sub, t)

    descricao = restricoes_entre_parenteses(descricao)
    for m in _RESTRICOES.finditer(descricao):
        saida.restricoes.append(m.group(0).strip(" ;,."))
    for frag in _ALINEA.split(descricao):
        _ler_fragmento(frag, coluna=False, saida=saida)
    if coluna.strip():
        for frag in re.split(r";", restricoes_entre_parenteses(coluna)):
            _ler_fragmento(frag, coluna=True, saida=saida)
    saida.incluidos = list(dict.fromkeys(saida.incluidos))
    saida.excluidos = list(dict.fromkeys(saida.excluidos))
    saida.restricoes = list(dict.fromkeys(r for r in saida.restricoes if r))
    return saida


# ------------------------------------------------------------------ nomenclatura --
class Nomenclatura:
    def __init__(self, nos: list[tuple[str, bool, str]]) -> None:
        self.folhas = sorted(c for c, folha, _ in nos if folha)
        self.codigos = {c for c, _, _ in nos}
        self.descricoes = {c: d for c, _, d in nos}

    def folhas_de(self, prefixo: str) -> list[str]:
        i = bisect.bisect_left(self.folhas, prefixo)
        saida = []
        while i < len(self.folhas) and self.folhas[i].startswith(prefixo):
            saida.append(self.folhas[i])
            i += 1
        return saida

    def expandir(self, prefixos: list[str]) -> set[str]:
        return {f for p in prefixos for f in self.folhas_de(p)}

    def existe(self, codigo: str) -> bool:
        return codigo in self.codigos or bool(self.folhas_de(codigo))


def _efetivos(nom: Nomenclatura, r: LegalRule) -> set[str]:
    inc = nom.expandir([c["codigo"] for c in (r.abrangencia or {}).get("codigos", [])])
    return inc - nom.expandir([e["codigo"] for e in r.excecoes or [] if e.get("codigo")])


@dataclass
class _RegraIndexada:
    slug: str
    cclasstrib: str | None
    dispositivo: str
    provision_id: Any
    tem_condicoes: bool


class ContextoDivergencias:
    """Dados compartilhados carregados uma vez (nomenclaturas, índice de cobertura das regras)."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.nom: dict[str, Nomenclatura | None] = {}
        for tipo, modelo, fonte in (("ncm", NcmNode, FonteReferencia.NCM), ("nbs", NbsNode, FonteReferencia.NBS)):
            v = versao_ativa(session, fonte)
            self.nom[tipo] = (
                Nomenclatura(
                    [
                        (c, bool(f), d or "")
                        for c, f, d in session.execute(
                            select(modelo.codigo, modelo.folha, modelo.descricao_completa).where(
                                modelo.version_id == v.id
                            )
                        )
                    ]
                )
                if v
                else None
            )
        v_cct = versao_ativa(session, FonteReferencia.CCLASSTRIB)
        self.cclasstrib: dict[str, CClassTribCode] = (
            {c.codigo: c for c in session.scalars(select(CClassTribCode).where(CClassTribCode.version_id == v_cct.id))}
            if v_cct
            else {}
        )
        self.provisoes: dict[Any, LegalProvision | None] = {}
        # Cobertura efetiva (folhas) de cada regra vigente ou em revisão, pela versão mais recente do slug.
        self.cobertura: dict[str, dict[str, list[_RegraIndexada]]] = {
            "ncm": defaultdict(list),
            "nbs": defaultdict(list),
        }
        self.por_provisao: dict[Any, dict[str, set[str]]] = defaultdict(dict)
        self.por_anexo: dict[tuple[str, str], set[str]] = defaultdict(set)
        ultimas: dict[str, LegalRule] = {}
        for r in session.scalars(
            select(LegalRule)
            .where(LegalRule.status.in_([StatusRegra.PENDENTE_REVISAO, StatusRegra.INVALIDA, StatusRegra.APROVADA]))
            .order_by(LegalRule.slug, LegalRule.versao)
        ):
            ultimas[r.slug] = r
        for r in ultimas.values():
            self.indexar(r)

    def indexar(self, r: LegalRule) -> None:
        tipo = r.tipo_codigo
        nom = self.nom.get(tipo or "")
        if nom is None or tipo is None or (r.abrangencia or {}).get("universal"):
            return
        if r.tipo_tratamento == TipoTratamento.IMPOSTO_SELETIVO:
            return
        idx = _RegraIndexada(r.slug, r.cclasstrib, r.dispositivo_legal, r.provision_id, bool(r.condicoes))
        efetivos = _efetivos(nom, r)
        if r.provision_id:
            self.por_provisao[r.provision_id][r.slug] = efetivos
        if r.anexo:
            self.por_anexo[(tipo, r.anexo)] |= efetivos
        for f in efetivos:
            self.cobertura[tipo][f] = [x for x in self.cobertura[tipo][f] if x.slug != r.slug] + [idx]

    def provisao(self, pid: Any) -> LegalProvision | None:
        if pid not in self.provisoes:
            self.provisoes[pid] = self.session.get(LegalProvision, pid)
        return self.provisoes[pid]


# ------------------------------------------------------------------ análise --
def _tratamento_do_titulo(titulo: str) -> str | None:
    t = _norm(titulo)
    if "imposto seletivo" in t:
        return None
    if "reducao a zero" in t or "aliquota zero" in t or "reducao de 100" in t:
        return TipoTratamento.ALIQUOTA_ZERO
    if "isenc" in t or "isent" in t:
        return TipoTratamento.ISENCAO
    for pct, trat in (
        ("60", TipoTratamento.REDUCAO_60),
        ("30", TipoTratamento.REDUCAO_30),
        ("40", TipoTratamento.REDUCAO_40),
    ):
        if re.search(rf"\b{pct}\b", t):
            return trat
    return None


def _fmt(tipo: str, c: str) -> str:
    from app.core.codes import formatar_codigo

    return formatar_codigo(tipo, c)


# alta/media exigem justificativa na aprovação; info só orienta a revisão.
GRAVIDADE = {
    "DIV_SOBREPOSICAO": "info",
    "DIV_SEM_TEXTO_LEGAL": "info",
    "DIV_TRATAMENTO": "media",
    "DIV_RESTRICAO_TEXTUAL": "media",
    "DIV_LEI_CODIGO_INEXISTENTE": "media",
    "DIV_ANEXO": "media",
}


def exige_justificativa(avisos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in avisos or [] if a.get("divergencia") and a.get("gravidade") != "info"]


def _aviso(codigo: str, mensagem: str, codigos: list[str] | None = None, acao: str | None = None) -> dict[str, Any]:
    a: dict[str, Any] = {
        "codigo": codigo,
        "mensagem": mensagem,
        "divergencia": True,
        "gravidade": GRAVIDADE.get(codigo, "alta"),
    }
    if codigos:
        a["codigos"] = sorted(codigos)[:MAX_CODIGOS_AVISO]
        a["total_codigos"] = len(codigos)
    if acao:
        a["acao"] = acao
    return a


def _lista(tipo: str, codigos: list[str] | set[str], n: int = 6) -> str:
    cs = sorted(codigos)
    txt = ", ".join(_fmt(tipo, c) for c in cs[:n])
    return txt + (f" e mais {len(cs) - n}" if len(cs) > n else "")


# Grupos zoológicos/botânicos citados pela lei cujos membros a tabela NCM descreve por nome.
_SINONIMOS = {"salmonideo": ("salm", "truta"), "atum": ("thunnu",), "bacalhau": ("gadu",)}


def _casa_termo(descricao: str, termos: list[str]) -> bool:
    # Só os dois últimos níveis: os níveis de cima listam muitas espécies e casariam com tudo.
    final = " › ".join(descricao.split(" › ")[-2:])
    d = " ".join(_radical(w) for w in _norm(final).split())
    return any(t in d for termo in termos for t in (termo, *_SINONIMOS.get(termo, ())) if t)


def detectar_divergencias(ctx: ContextoDivergencias, r: LegalRule) -> list[dict[str, Any]]:
    """Lista de avisos de divergência (vazia quando a regra confere com a lei e a tabela oficial)."""
    abr = r.abrangencia or {}
    if abr.get("universal") or not r.tipo_codigo:
        return []
    tipo = r.tipo_codigo
    nom = ctx.nom.get(tipo)
    if nom is None:
        return []
    avisos: list[dict[str, Any]] = []

    # Anexo e tratamento: tabela cClassTrib × regra × título do anexo na lei
    cct = ctx.cclasstrib.get(r.cclasstrib or "")
    if cct is not None and cct.nro_anexo and r.anexo:
        anexo_cct = ROMANOS[cct.nro_anexo - 1] if cct.nro_anexo <= len(ROMANOS) else str(cct.nro_anexo)
        if anexo_cct != r.anexo:
            avisos.append(
                _aviso(
                    "DIV_ANEXO",
                    f"A regra está no Anexo {r.anexo}, mas a tabela oficial associa o cClassTrib {cct.codigo} "
                    f"ao Anexo {anexo_cct}.",
                )
            )

    prov = ctx.provisao(r.provision_id) if r.provision_id else None
    if prov is None:
        if r.anexo and r.tipo_tratamento != TipoTratamento.IMPOSTO_SELETIVO:
            avisos.append(
                _aviso(
                    "DIV_SEM_TEXTO_LEGAL",
                    "Não foi possível localizar o item correspondente no texto da LC 214/2025; a conferência "
                    "automática dos códigos contra a lei não foi feita. Confira manualmente.",
                )
            )
        return avisos

    trat_lei = _tratamento_do_titulo(prov.titulo_anexo or "")
    if trat_lei and r.tipo_tratamento not in (trat_lei, TipoTratamento.IMPOSTO_SELETIVO) and not r.condicoes:
        situacao = f" para uma situação específica: “{cct.nome[:220]}”" if cct is not None else ""
        avisos.append(
            _aviso(
                "DIV_TRATAMENTO",
                f"O título do Anexo {prov.anexo} prevê '{trat_lei.replace('_', ' ')}', mas o cClassTrib "
                f"{r.cclasstrib} aplica '{str(r.tipo_tratamento).replace('_', ' ')}'{situacao}. A regra não "
                "tem condição que a limite a essa situação; sem ela, todo item destes códigos teria dois "
                "enquadramentos possíveis. Adicione a condição (ex.: tipo de adquirente ou operação).",
            )
        )

    lei = ler_texto_legal(prov.texto)
    if lei.restricoes and not r.condicoes and not any(not e.get("codigo") for e in r.excecoes or []):
        avisos.append(
            _aviso(
                "DIV_RESTRICAO_TEXTUAL",
                "A lei restringe o benefício em palavras, e a regra não tem condição nem exceção textual: "
                + "; ".join(f"“{x[:160]}”" for x in lei.restricoes[:4]),
            )
        )
    if not lei.todos_codigos:
        return avisos

    inexistentes = [c for c in lei.todos_codigos if not nom.existe(c)]
    if inexistentes:
        avisos.append(
            _aviso(
                "DIV_LEI_CODIGO_INEXISTENTE",
                f"A lei cita códigos que não existem na tabela {tipo.upper()} vigente (provável renumeração "
                f"da tabela): {_lista(tipo, inexistentes)}. Confira qual código atual corresponde.",
            )
        )

    lei_inc = nom.expandir(lei.incluidos)
    lei_exc = nom.expandir(lei.excluidos)
    for anexo in dict.fromkeys(lei.anexos_excluidos):
        if anexo != r.anexo:
            lei_exc |= ctx.por_anexo.get((tipo, anexo), set()) & lei_inc
    parciais: dict[str, ExcecaoParcial] = {}
    for p in lei.parciais:
        for f in nom.expandir(p.codigos):
            parciais.setdefault(f, p)
    regra_inc = nom.expandir([c["codigo"] for c in abr.get("codigos", [])])
    regra_exc = nom.expandir([e["codigo"] for e in r.excecoes or [] if e.get("codigo")])
    regra_ef = regra_inc - regra_exc

    # Folhas cobertas por outra regra do mesmo item da lei (a lei pode ser dividida em vários cClassTrib).
    irmas: set[str] = set()
    for slug, fs in ctx.por_provisao.get(r.provision_id, {}).items():
        if slug != r.slug:
            irmas |= fs

    alem = regra_ef - lei_inc
    if alem:
        avisos.append(
            _aviso(
                "DIV_ALEM_DA_LEI",
                f"{len(alem)} código(s) recebem o benefício na regra, mas não estão entre os citados pelo item "
                f"da lei: {_lista(tipo, alem)}.",
                sorted(alem),
                "remover_da_abrangencia",
            )
        )

    contra = (regra_ef & lei_exc) | {
        f for f in regra_ef & set(parciais) if _casa_termo(nom.descricoes.get(f, ""), parciais[f].termos)
    }
    if contra:
        avisos.append(
            _aviso(
                "DIV_EXCECAO_DA_LEI_IGNORADA",
                f"A lei exclui expressamente {len(contra)} código(s) que a regra beneficia: {_lista(tipo, contra)}.",
                sorted(contra),
                "adicionar_excecao",
            )
        )

    parcial_ampliada = {
        f
        for f in (lei_inc & set(parciais)) - regra_ef - lei_exc - irmas
        if not _casa_termo(nom.descricoes.get(f, ""), parciais[f].termos)
    }
    if parcial_ampliada:
        descritores = "; ".join(dict.fromkeys(f"“{parciais[f].descritor[:120]}”" for f in parcial_ampliada))
        avisos.append(
            _aviso(
                "DIV_EXCECAO_PARCIAL_AMPLIADA",
                f"A lei exclui apenas certos produtos dentro destes códigos ({descritores}), mas a regra deixa "
                f"de fora o código inteiro. {len(parcial_ampliada)} código(s) cuja descrição oficial não cita "
                f"esses produtos ficaram sem o benefício: {_lista(tipo, parcial_ampliada)}. Avalie incluí-los "
                "(com condição ou como caso controverso) ou justifique a exclusão.",
                sorted(parcial_ampliada),
                "incluir_na_abrangencia",
            )
        )

    lei_certa = lei_inc - lei_exc - set(parciais) - irmas
    vetados = (lei_certa & regra_exc) - regra_ef
    if vetados:
        avisos.append(
            _aviso(
                "DIV_VETO_SEM_BASE_NA_LEI",
                f"A tabela oficial veta {len(vetados)} código(s) que a lei inclui sem exceção: "
                f"{_lista(tipo, vetados)}.",
                sorted(vetados),
                "incluir_na_abrangencia",
            )
        )
    faltando = lei_certa - regra_inc - regra_exc
    if faltando:
        avisos.append(
            _aviso(
                "DIV_LEI_NAO_COBERTA",
                f"A lei inclui {len(faltando)} código(s) que a regra não abrange: {_lista(tipo, faltando)}.",
                sorted(faltando),
                "incluir_na_abrangencia",
            )
        )

    # Sobreposição com regras de outros itens e outro cClassTrib. Condições em qualquer das regras
    # podem diferenciá-las, então só se acusa quando nenhuma das duas tem condição.
    if not r.condicoes:
        conflitos: dict[str, set[str]] = defaultdict(set)
        for f in regra_ef:
            for x in ctx.cobertura[tipo].get(f, []):
                if (
                    x.slug != r.slug
                    and r.cclasstrib
                    and x.cclasstrib
                    and not x.tem_condicoes
                    and x.cclasstrib != r.cclasstrib
                    and x.provision_id != r.provision_id
                ):
                    conflitos[f"{x.dispositivo} (cClassTrib {x.cclasstrib or '—'})"].add(f)
        if conflitos:
            todos = set().union(*conflitos.values())
            outras = sorted(conflitos, key=lambda k: -len(conflitos[k]))
            avisos.append(
                _aviso(
                    "DIV_SOBREPOSICAO",
                    f"{len(todos)} código(s) desta regra também recebem outro tratamento por "
                    f"{len(outras)} outra(s) regra(s): "
                    + "; ".join(f"{k} — {_lista(tipo, conflitos[k], 3)}" for k in outras[:4])
                    + (f"; e mais {len(outras) - 4}" if len(outras) > 4 else "")
                    + ". Sem condição que as diferencie (ex.: destinação do produto), itens nesses códigos irão "
                    "para análise humana.",
                    sorted(todos),
                )
            )
    return avisos
