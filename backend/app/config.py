"""Configuração da aplicação, lida exclusivamente de variáveis de ambiente."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    ambiente: Literal["desenvolvimento", "teste", "producao"] = Field("desenvolvimento", alias="APP_ENV")
    app_nome: str = "Auditor Fiscal de Cadastros"
    base_url_frontend: str = Field("http://localhost:5180", alias="FRONTEND_URL")
    cors_origens: list[str] = Field(default_factory=lambda: ["http://localhost:5180"], alias="CORS_ORIGINS")

    # Banco de dados. A aplicação usa um papel SEM BYPASSRLS; a base de referência é escrita
    # por um papel separado; migrações rodam com o dono do schema.
    database_url: str = Field(..., alias="DATABASE_URL")
    reference_admin_database_url: str = Field(..., alias="REFERENCE_ADMIN_DATABASE_URL")
    migrations_database_url: str = Field("", alias="MIGRATIONS_DATABASE_URL")
    db_pool_size: int = Field(10, alias="DB_POOL_SIZE")

    redis_url: str = Field("redis://redis:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field("redis://redis:6379/1", alias="CELERY_BROKER_URL")

    # Segurança
    jwt_secret: SecretStr = Field(..., alias="JWT_SECRET")
    jwt_access_minutes: int = Field(15, alias="JWT_ACCESS_MINUTES")
    refresh_token_days: int = Field(14, alias="REFRESH_TOKEN_DAYS")
    cookie_secure: bool = Field(True, alias="COOKIE_SECURE")
    login_max_tentativas: int = Field(5, alias="LOGIN_MAX_ATTEMPTS")
    login_bloqueio_minutos: int = Field(15, alias="LOGIN_LOCKOUT_MINUTES")
    rate_limit_por_minuto: int = Field(600, alias="RATE_LIMIT_PER_MINUTE")

    # Armazenamento de arquivos enviados
    storage_dir: Path = Field(Path("/data/storage"), alias="STORAGE_DIR")
    upload_max_mb: int = Field(50, alias="UPLOAD_MAX_MB")
    upload_max_linhas: int = Field(100_000, alias="UPLOAD_MAX_ROWS")

    # Anthropic. A chave só existe no servidor.
    anthropic_api_key: SecretStr | None = Field(None, alias="ANTHROPIC_API_KEY")
    # Outras plataformas (opcional: as chaves cadastradas na tela "Chaves de API" têm precedência).
    openai_api_key: SecretStr | None = Field(None, alias="OPENAI_API_KEY")
    deepseek_api_key: SecretStr | None = Field(None, alias="DEEPSEEK_API_KEY")
    # Segredo que cifra as chaves de API guardadas no banco. Se vazio, deriva do JWT_SECRET
    # (trocar o JWT_SECRET, nesse caso, exige cadastrar as chaves de novo).
    llm_keys_secret: SecretStr | None = Field(None, alias="LLM_KEYS_SECRET")
    llm_model_primary: str = Field("claude-haiku-4-5-20251001", alias="LLM_MODEL_PRIMARY")
    llm_model_escalation: str = Field("claude-sonnet-5", alias="LLM_MODEL_ESCALATION")
    llm_model_light: str = Field("claude-haiku-4-5-20251001", alias="LLM_MODEL_LIGHT")
    llm_effort_primary: Literal["low", "medium", "high", "xhigh", "max"] = Field("medium", alias="LLM_EFFORT_PRIMARY")
    llm_effort_escalation: Literal["low", "medium", "medium", "xhigh", "max"] = Field(
        "medium", alias="LLM_EFFORT_ESCALATION"
    )
    # Investigação jurídica por família (modelo de escalonamento): esforço médio equilibra custo e rigor.
    llm_effort_investigation: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        "medium", alias="LLM_EFFORT_INVESTIGATION"
    )
    llm_timeout_s: float = Field(120.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_tentativas: int = Field(5, alias="LLM_MAX_RETRIES")
    llm_batch_min_itens: int = Field(200, alias="LLM_BATCH_MIN_ITEMS")
    llm_batch_poll_s: int = Field(30, alias="LLM_BATCH_POLL_SECONDS")

    # Embeddings locais (Hugging Face Text Embeddings Inference)
    embeddings_url: str = Field("http://embeddings:80", alias="EMBEDDINGS_URL")
    embeddings_modelo: str = Field("intfloat/multilingual-e5-base", alias="EMBEDDINGS_MODEL")
    embeddings_dim: int = Field(768, alias="EMBEDDINGS_DIM")
    embeddings_lote: int = Field(32, alias="EMBEDDINGS_BATCH")
    # Modelos da família E5 exigem prefixos ("query: " / "passage: "); o bge-m3 não usa prefixo.
    embeddings_prefixo_consulta: str = Field("", alias="EMBEDDINGS_QUERY_PREFIX")
    embeddings_prefixo_documento: str = Field("", alias="EMBEDDINGS_PASSAGE_PREFIX")

    # Fontes oficiais (podem mudar; o upload manual é sempre aceito)
    fonte_ncm_url: str = Field(
        "https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json?perfil=PUBLICO",
        alias="SOURCE_NCM_URL",
    )
    fonte_nbs_url: str = Field(
        "https://www.gov.br/mdic/pt-br/images/REPOSITORIO/scs/decos/NBS/NBSa_2-0.csv", alias="SOURCE_NBS_URL"
    )
    fonte_cclasstrib_url: str = Field(
        "https://dfe-portal.svrs.rs.gov.br/CFF/ClassificacaoTributaria", alias="SOURCE_CCLASSTRIB_URL"
    )
    fonte_lc214_url: str = Field("https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm", alias="SOURCE_LC214_URL")
    http_user_agent: str = Field(
        "Mozilla/5.0 (compatible; AuditorFiscalCadastros/1.0; +https://example.invalid)",
        alias="HTTP_USER_AGENT",
    )

    # Retenção (LGPD)
    retencao_arquivos_dias_padrao: int = Field(30, alias="RETENTION_FILES_DAYS")

    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @property
    def em_producao(self) -> bool:
        return self.ambiente == "producao"


@lru_cache
def get_settings() -> Settings:
    return Settings()
