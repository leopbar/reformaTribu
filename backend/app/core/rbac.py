"""Permissões por papel."""

from __future__ import annotations

from enum import StrEnum

from app.models.enums import Papel


class Perm(StrEnum):
    VER = "ver"
    GERENCIAR_USUARIOS = "gerenciar_usuarios"
    GERENCIAR_EMPRESAS = "gerenciar_empresas"
    GERENCIAR_CONFIGURACOES = "gerenciar_configuracoes"
    ENVIAR_PLANILHA = "enviar_planilha"
    CRIAR_AUDITORIA = "criar_auditoria"
    REVISAR = "revisar"
    # Responder perguntas do analista e manter o dossiê (fatos simples sobre produtos e loja).
    RESPONDER = "responder"
    EXPORTAR = "exportar"
    VER_LOG = "ver_log"
    GERENCIAR_ABREVIACOES = "gerenciar_abreviacoes"


PERMISSOES: dict[str, frozenset[Perm]] = {
    Papel.ADMINISTRADOR: frozenset(Perm),
    Papel.REVISOR: frozenset(
        {
            Perm.VER,
            Perm.ENVIAR_PLANILHA,
            Perm.CRIAR_AUDITORIA,
            Perm.REVISAR,
            Perm.RESPONDER,
            Perm.EXPORTAR,
            Perm.GERENCIAR_ABREVIACOES,
        }
    ),
    Papel.OPERADOR: frozenset({Perm.VER, Perm.ENVIAR_PLANILHA, Perm.CRIAR_AUDITORIA, Perm.RESPONDER}),
    Papel.LEITURA: frozenset({Perm.VER}),
}


def tem_permissao(papel: str | None, perm: Perm) -> bool:
    return papel is not None and perm in PERMISSOES.get(papel, frozenset())


def permissoes_do_papel(papel: str | None) -> list[str]:
    return sorted(p.value for p in PERMISSOES.get(papel or "", frozenset()))
