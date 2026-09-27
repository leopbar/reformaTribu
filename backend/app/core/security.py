"""Senhas (Argon2id), tokens de acesso (JWT curto) e refresh tokens opacos."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

_hasher = PasswordHasher()  # Argon2id com parâmetros padrão recomendados (RFC 9106)
_HASH_FALSO = _hasher.hash("senha-inexistente-para-tempo-constante")

SENHA_MIN = 12


def hash_senha(senha: str) -> str:
    return _hasher.hash(senha)


def verificar_senha(senha: str, hash_: str | None) -> bool:
    try:
        return _hasher.verify(hash_ or _HASH_FALSO, senha) and hash_ is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def precisa_rehash(hash_: str) -> bool:
    return _hasher.check_needs_rehash(hash_)


def validar_forca_senha(senha: str) -> str | None:
    """Devolve uma mensagem de erro em português ou None se a senha é aceitável."""
    if len(senha) < SENHA_MIN:
        return f"A senha precisa ter pelo menos {SENHA_MIN} caracteres."
    classes = sum(
        [
            any(c.islower() for c in senha),
            any(c.isupper() for c in senha),
            any(c.isdigit() for c in senha),
            any(not c.isalnum() for c in senha),
        ]
    )
    if classes < 3:
        return "Use ao menos três tipos de caractere: minúsculas, maiúsculas, números e símbolos."
    return None


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    org_id: uuid.UUID | None
    papel: str | None
    platform_admin: bool
    email: str


def criar_access_token(claims: AccessClaims) -> tuple[str, int]:
    s = get_settings()
    agora = datetime.now(UTC)
    exp = agora + timedelta(minutes=s.jwt_access_minutes)
    payload: dict[str, Any] = {
        "sub": str(claims.user_id),
        "org": str(claims.org_id) if claims.org_id else None,
        "papel": claims.papel,
        "adm": claims.platform_admin,
        "email": claims.email,
        "iat": int(agora.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "access",
    }
    token = jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm="HS256")
    return token, s.jwt_access_minutes * 60


def decodificar_access_token(token: str) -> AccessClaims | None:
    try:
        p = jwt.decode(
            token,
            get_settings().jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    if p.get("typ") != "access":
        return None
    return AccessClaims(
        user_id=uuid.UUID(p["sub"]),
        org_id=uuid.UUID(p["org"]) if p.get("org") else None,
        papel=p.get("papel"),
        platform_admin=bool(p.get("adm")),
        email=p.get("email", ""),
    )


def novo_refresh_token() -> tuple[str, str]:
    """Devolve (token em claro para o cookie, hash SHA-256 para o banco)."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh(token)


def hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def novo_csrf_token() -> str:
    return secrets.token_urlsafe(32)
