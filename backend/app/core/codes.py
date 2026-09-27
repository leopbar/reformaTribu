"""Normalização e formatação de códigos fiscais (NCM, NBS, CNPJ, GTIN, CST, cClassTrib)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NAO_DIGITO = re.compile(r"\D")
_NAO_ALFANUM = re.compile(r"[^0-9A-Za-z]")


def somente_digitos(valor: object) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip()
    # Planilhas às vezes trazem números como "4011000.0"
    if re.fullmatch(r"\d+\.0+", texto):
        texto = texto.split(".")[0]
    return _NAO_DIGITO.sub("", texto)


# ------------------------------------------------------------------------------ NCM ----
def nivel_ncm(codigo: str) -> str:
    return {2: "capitulo", 4: "posicao", 5: "subposicao", 6: "subposicao", 7: "item", 8: "subitem"}.get(
        len(codigo), "desconhecido"
    )


def formatar_ncm(codigo: str | None) -> str:
    """Formata dígitos de NCM: 34011190 → 3401.11.90; 0306.1 → 0306.1."""
    if not codigo:
        return ""
    c = somente_digitos(codigo)
    if len(c) <= 2:
        return c
    if len(c) <= 4:
        return c
    if len(c) <= 6:
        return f"{c[:4]}.{c[4:]}"
    return f"{c[:4]}.{c[4:6]}.{c[6:]}"


@dataclass
class NcmNormalizado:
    original: str
    codigo: str | None
    problemas: list[dict[str, str]] = field(default_factory=list)
    candidato_zero_esquerda: str | None = None


def normalizar_ncm(valor: object) -> NcmNormalizado:
    """Remove pontuação e sinaliza (sem corrigir em silêncio) zeros à esquerda perdidos."""
    original = "" if valor is None else str(valor).strip()
    if not original:
        return NcmNormalizado(original="", codigo=None)
    digitos = somente_digitos(original)
    res = NcmNormalizado(original=original, codigo=digitos or None)
    if not digitos:
        res.problemas.append({"codigo": "NCM_INVALIDO", "mensagem": "O NCM informado não contém dígitos."})
        return res
    if len(digitos) == 7:
        # Provável zero à esquerda perdido pelo Excel (ex.: 4011000 → 04011000).
        res.candidato_zero_esquerda = "0" + digitos
        res.problemas.append(
            {
                "codigo": "NCM_ZERO_A_ESQUERDA_SUSPEITO",
                "mensagem": f"NCM com 7 dígitos; provavelmente {formatar_ncm('0' + digitos)} "
                "(zero à esquerda perdido na planilha).",
            }
        )
    elif len(digitos) < 8:
        res.problemas.append(
            {
                "codigo": "NCM_NIVEL_INCOMPLETO",
                "mensagem": f"NCM com {len(digitos)} dígitos; o cadastro exige o código completo de 8 dígitos.",
            }
        )
    elif len(digitos) > 8:
        res.problemas.append({"codigo": "NCM_INVALIDO", "mensagem": f"NCM com {len(digitos)} dígitos (o máximo é 8)."})
    return res


# ------------------------------------------------------------------------------ NBS ----
def formatar_nbs(codigo: str | None) -> str:
    """Formata NBS: 101011100 → 1.0101.11.00."""
    if not codigo:
        return ""
    c = somente_digitos(codigo)
    if len(c) <= 1:
        return c
    partes = [c[0], c[1:5]]
    resto = c[5:]
    if resto:
        partes.append(resto[:2] if len(resto) > 1 else resto)
    if len(resto) > 2:
        partes.append(resto[2:])
    return ".".join(p for p in partes if p)


def nivel_nbs(codigo: str) -> str:
    return {1: "secao", 3: "capitulo", 5: "posicao", 6: "subposicao", 7: "subposicao", 9: "item"}.get(
        len(codigo), "desconhecido"
    )


def normalizar_nbs(valor: object) -> tuple[str | None, list[dict[str, str]]]:
    original = "" if valor is None else str(valor).strip()
    if not original:
        return None, []
    d = somente_digitos(original)
    problemas: list[dict[str, str]] = []
    if len(d) != 9:
        problemas.append(
            {
                "codigo": "NBS_NIVEL_INCOMPLETO",
                "mensagem": f"NBS com {len(d)} dígitos; o código completo tem 9 dígitos (ex.: 1.0101.11.00).",
            }
        )
    return d or None, problemas


def formatar_codigo(tipo: str | None, codigo: str | None) -> str:
    return formatar_nbs(codigo) if tipo == "nbs" else formatar_ncm(codigo)


# ----------------------------------------------------------------------------- GTIN ----
def gtin_valido(valor: object) -> bool:
    d = somente_digitos(valor)
    if len(d) not in (8, 12, 13, 14) or set(d) == {"0"}:
        return False
    corpo, dv = d[:-1], int(d[-1])
    soma = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(corpo)))
    return (10 - soma % 10) % 10 == dv


# ----------------------------------------------------------------------------- CNPJ ----
_PESOS_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_PESOS_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def normalizar_cnpj(valor: object) -> str:
    return _NAO_ALFANUM.sub("", str(valor or "")).upper()


def _dv_cnpj(base: str, pesos: list[int]) -> int:
    # CNPJ alfanumérico (IN RFB nº 2.229/2024): valor do caractere = código ASCII − 48.
    soma = sum((ord(c) - 48) * p for c, p in zip(base, pesos, strict=True))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def cnpj_valido(valor: object) -> bool:
    c = normalizar_cnpj(valor)
    if len(c) != 14 or not re.fullmatch(r"[0-9A-Z]{12}\d{2}", c):
        return False
    if c.isdigit() and len(set(c)) == 1:
        return False
    d1 = _dv_cnpj(c[:12], _PESOS_1)
    d2 = _dv_cnpj(c[:12] + str(d1), _PESOS_2)
    return c[12:] == f"{d1}{d2}"


def formatar_cnpj(valor: str) -> str:
    c = normalizar_cnpj(valor)
    if len(c) != 14:
        return c
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


# ---------------------------------------------------------------------- CST/cClassTrib --
def normalizar_cst(valor: object) -> str | None:
    d = somente_digitos(valor)
    return d.zfill(3) if d and len(d) <= 3 else (d or None)


def normalizar_cclasstrib(valor: object) -> str | None:
    d = somente_digitos(valor)
    return d.zfill(6) if d and len(d) <= 6 else (d or None)
