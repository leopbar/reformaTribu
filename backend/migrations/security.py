"""SQL de segurança aplicado pela migração inicial: RLS, permissões e gatilhos de imutabilidade.

Mantido em módulo separado para ser legível e testável. Ver docs/arquitetura.md, seção "Isolamento".
"""

from __future__ import annotations

TENANT_TABLES_SIMPLES = (
    "org_settings",
    "company_access",
    "companies",
    "mapping_templates",
    "uploaded_files",
    "audits",
    "audit_items",
    "item_candidates",
    "item_reviews",
    "approved_memory",
    "llm_batches",
    "export_jobs",
    "export_layouts",
    "notifications",
)

REFERENCE_TABLES = (
    "ref_versions",
    "ncm_nodes",
    "nbs_nodes",
    "cst_codes",
    "cclasstrib_codes",
    "cclasstrib_correlacoes",
    "legal_provisions",
    "legal_rules",
    "legal_rule_codes",
    "condition_attributes",
)

PRE_TABLES = r"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION public.immutable_unaccent(text) RETURNS text
  AS $f$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $f$
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT;

CREATE OR REPLACE FUNCTION public.app_org_id() RETURNS uuid LANGUAGE sql STABLE AS
  $f$ SELECT NULLIF(current_setting('app.org_id', true), '')::uuid $f$;
CREATE OR REPLACE FUNCTION public.app_user_id() RETURNS uuid LANGUAGE sql STABLE AS
  $f$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $f$;
CREATE OR REPLACE FUNCTION public.app_is_platform_admin() RETURNS boolean LANGUAGE sql STABLE AS
  $f$ SELECT COALESCE(NULLIF(current_setting('app.platform_admin', true), ''), 'false')::boolean $f$;
"""


def post_tables_sql() -> str:
    partes: list[str] = []

    # --- Permissões básicas -----------------------------------------------------------------
    partes.append(
        """
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO reforma_app, reforma_ref;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO reforma_app, reforma_ref;
"""
    )
    for t in REFERENCE_TABLES:
        partes.append(f"GRANT SELECT ON {t} TO reforma_app;")
        partes.append(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO reforma_ref;")
    # Snapshots são criados pela aplicação no início de cada auditoria (somente inserção).
    partes.append("GRANT SELECT, INSERT ON ref_snapshots TO reforma_app, reforma_ref;")

    for t in TENANT_TABLES_SIMPLES:
        if t == "item_reviews":
            partes.append(f"GRANT SELECT, INSERT ON {t} TO reforma_app;")
        else:
            partes.append(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO reforma_app;")
    partes.append(
        """
GRANT SELECT, INSERT, UPDATE, DELETE ON organizations, memberships, users, abbreviations, llm_calls TO reforma_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON refresh_tokens TO reforma_app;
GRANT SELECT, INSERT ON audit_log TO reforma_app, reforma_ref;
GRANT SELECT, INSERT, UPDATE ON llm_calls TO reforma_ref;
GRANT SELECT ON users, organizations TO reforma_ref;
GRANT SELECT, INSERT, UPDATE ON abbreviations TO reforma_ref;
"""
    )

    # --- Row-Level Security ---------------------------------------------------------------
    for t in TENANT_TABLES_SIMPLES:
        partes.append(
            f"""
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {t}
  USING (org_id = app_org_id()) WITH CHECK (org_id = app_org_id());
"""
        )

    partes.append(
        r"""
-- Vínculos: o usuário enxerga os próprios vínculos (para trocar de organização).
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY memberships_select ON memberships FOR SELECT
  USING (org_id = app_org_id() OR user_id = app_user_id());
CREATE POLICY memberships_write ON memberships FOR ALL
  USING (org_id = app_org_id()) WITH CHECK (org_id = app_org_id());

-- Organizações: visíveis para quem é membro; criação e exclusão só pelo superadministrador.
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;
CREATE POLICY organizations_select ON organizations FOR SELECT
  USING (id = app_org_id() OR app_is_platform_admin()
         OR EXISTS (SELECT 1 FROM memberships m WHERE m.org_id = organizations.id AND m.user_id = app_user_id()));
CREATE POLICY organizations_insert ON organizations FOR INSERT WITH CHECK (app_is_platform_admin());
CREATE POLICY organizations_update ON organizations FOR UPDATE
  USING (id = app_org_id() OR app_is_platform_admin()) WITH CHECK (id = app_org_id() OR app_is_platform_admin());
CREATE POLICY organizations_delete ON organizations FOR DELETE USING (app_is_platform_admin());

-- Usuários: o próprio usuário, membros da organização atual, ou o superadministrador.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY users_select ON users FOR SELECT
  USING (id = app_user_id() OR app_is_platform_admin()
         OR EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = users.id AND m.org_id = app_org_id()));
CREATE POLICY users_insert ON users FOR INSERT WITH CHECK (app_org_id() IS NOT NULL OR app_is_platform_admin());
CREATE POLICY users_update ON users FOR UPDATE
  USING (id = app_user_id() OR app_is_platform_admin()
         OR EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = users.id AND m.org_id = app_org_id()));

-- Dicionário de abreviações: global (org_id nulo) + específico da organização.
ALTER TABLE abbreviations ENABLE ROW LEVEL SECURITY;
ALTER TABLE abbreviations FORCE ROW LEVEL SECURITY;
CREATE POLICY abbreviations_select ON abbreviations FOR SELECT
  USING (org_id IS NULL OR org_id = app_org_id());
CREATE POLICY abbreviations_write ON abbreviations FOR ALL
  USING (org_id = app_org_id() OR (org_id IS NULL AND app_is_platform_admin()))
  WITH CHECK (org_id = app_org_id() OR (org_id IS NULL AND app_is_platform_admin()));

-- Chamadas de IA: por organização; as de plataforma (org nulo) só para o superadministrador.
ALTER TABLE llm_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_calls FORCE ROW LEVEL SECURITY;
CREATE POLICY llm_calls_isolation ON llm_calls
  USING (org_id = app_org_id() OR (org_id IS NULL AND app_is_platform_admin()))
  WITH CHECK (org_id = app_org_id() OR (org_id IS NULL AND app_is_platform_admin()));

-- Log de auditoria.
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_log_select ON audit_log FOR SELECT
  USING (org_id = app_org_id() OR (org_id IS NULL AND app_is_platform_admin()));
CREATE POLICY audit_log_insert ON audit_log FOR INSERT
  WITH CHECK (org_id IS NULL OR org_id = app_org_id());

-- Funções de sistema (SECURITY DEFINER) que devolvem apenas identificadores, para que
-- tarefas agendadas saibam em quais organizações atuar; o trabalho em si roda com RLS.
CREATE OR REPLACE FUNCTION public.sys_orgs_com_trabalho() RETURNS TABLE(org_id uuid)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $f$
    SELECT DISTINCT a.org_id FROM audits a
     WHERE a.status IN ('processando', 'aguardando_lote', 'pausada_orcamento')
    UNION
    SELECT DISTINCT c.org_id FROM llm_calls c WHERE c.status IN ('na_fila', 'enviada') AND c.org_id IS NOT NULL
  $f$;
CREATE OR REPLACE FUNCTION public.sys_orgs_com_arquivos_a_expurgar() RETURNS TABLE(org_id uuid)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $f$
    SELECT DISTINCT f.org_id FROM uploaded_files f
     WHERE f.expurgado_em IS NULL AND f.expurgar_em IS NOT NULL AND f.expurgar_em <= current_date
  $f$;
CREATE OR REPLACE FUNCTION public.sys_buscar_login(p_email text)
  RETURNS TABLE(id uuid, password_hash text, ativo boolean, is_platform_admin boolean, nome text)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $f$
    SELECT u.id, u.password_hash, u.ativo, u.is_platform_admin, u.nome FROM users u
     WHERE u.email = p_email::citext
  $f$;
CREATE OR REPLACE FUNCTION public.sys_usuario_por_email(p_email text) RETURNS uuid
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $f$
    SELECT u.id FROM users u WHERE u.email = p_email::citext
  $f$;
REVOKE ALL ON FUNCTION public.sys_orgs_com_trabalho() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sys_orgs_com_arquivos_a_expurgar() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sys_buscar_login(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sys_usuario_por_email(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sys_orgs_com_trabalho() TO reforma_app;
GRANT EXECUTE ON FUNCTION public.sys_orgs_com_arquivos_a_expurgar() TO reforma_app;
GRANT EXECUTE ON FUNCTION public.sys_buscar_login(text) TO reforma_app;
GRANT EXECUTE ON FUNCTION public.sys_usuario_por_email(text) TO reforma_app;

-- Log de auditoria encadeado por hash e imutável.
CREATE OR REPLACE FUNCTION public.audit_log_encadear() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $f$
DECLARE anterior text;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('audit_log_encadear'));
  SELECT hash INTO anterior FROM audit_log ORDER BY id DESC LIMIT 1;
  NEW.hash_anterior := anterior;
  NEW.hash := encode(digest(
      coalesce(anterior, '') || '|' || NEW.acao || '|' || coalesce(NEW.org_id::text, '') || '|' ||
      coalesce(NEW.user_id::text, '') || '|' || coalesce(NEW.entidade, '') || '|' ||
      coalesce(NEW.entidade_id, '') || '|' || NEW.detalhes::text || '|' || NEW.created_at::text,
      'sha256'), 'hex');
  RETURN NEW;
END $f$;
CREATE TRIGGER audit_log_encadear BEFORE INSERT ON audit_log
  FOR EACH ROW EXECUTE FUNCTION public.audit_log_encadear();

CREATE OR REPLACE FUNCTION public.bloquear_alteracao() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('app.purga_autorizada', true) = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Registro imutável: % em % não é permitido', TG_OP, TG_TABLE_NAME
    USING ERRCODE = 'insufficient_privilege';
END $f$;
CREATE TRIGGER audit_log_imutavel BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION public.bloquear_alteracao();
CREATE TRIGGER item_reviews_imutavel BEFORE UPDATE ON item_reviews
  FOR EACH ROW EXECUTE FUNCTION public.bloquear_alteracao();

-- Busca vetorial aproximada sobre as descrições oficiais (somente códigos folha).
CREATE INDEX ix_ncm_nodes_embedding ON ncm_nodes USING hnsw (embedding vector_cosine_ops) WHERE folha;
CREATE INDEX ix_nbs_nodes_embedding ON nbs_nodes USING hnsw (embedding vector_cosine_ops) WHERE folha;
CREATE INDEX ix_ncm_nodes_version_folha ON ncm_nodes (version_id) WHERE folha;
CREATE INDEX ix_nbs_nodes_version_folha ON nbs_nodes (version_id) WHERE folha;
"""
    )
    return "\n".join(partes)


DOWNGRADE_SQL = r"""
DROP POLICY IF EXISTS organizations_select ON organizations;
DROP POLICY IF EXISTS users_select ON users;
DROP POLICY IF EXISTS users_update ON users;
DROP FUNCTION IF EXISTS public.sys_orgs_com_trabalho() CASCADE;
DROP FUNCTION IF EXISTS public.sys_orgs_com_arquivos_a_expurgar() CASCADE;
DROP FUNCTION IF EXISTS public.sys_buscar_login(text) CASCADE;
DROP FUNCTION IF EXISTS public.sys_usuario_por_email(text) CASCADE;
DROP FUNCTION IF EXISTS public.audit_log_encadear() CASCADE;
DROP FUNCTION IF EXISTS public.bloquear_alteracao() CASCADE;
"""

POST_DOWNGRADE_SQL = r"""
DROP FUNCTION IF EXISTS public.app_org_id() CASCADE;
DROP FUNCTION IF EXISTS public.app_user_id() CASCADE;
DROP FUNCTION IF EXISTS public.app_is_platform_admin() CASCADE;
DROP FUNCTION IF EXISTS public.immutable_unaccent(text) CASCADE;
"""
