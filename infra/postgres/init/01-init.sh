#!/bin/bash
# Cria os papéis da aplicação e as extensões. Executado só na primeira inicialização do volume.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'reforma_app') THEN
      CREATE ROLE reforma_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD '${APP_DB_PASSWORD}';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'reforma_ref') THEN
      CREATE ROLE reforma_ref LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD '${REF_DB_PASSWORD}';
    END IF;
  END
  \$\$;
  GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO reforma_app, reforma_ref;
  CREATE EXTENSION IF NOT EXISTS vector;
  CREATE EXTENSION IF NOT EXISTS unaccent;
  CREATE EXTENSION IF NOT EXISTS citext;
  CREATE EXTENSION IF NOT EXISTS pgcrypto;
  CREATE DATABASE "${POSTGRES_DB}_test" OWNER "$POSTGRES_USER";
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${POSTGRES_DB}_test" <<-SQL
  GRANT CONNECT ON DATABASE "${POSTGRES_DB}_test" TO reforma_app, reforma_ref;
  CREATE EXTENSION IF NOT EXISTS vector;
  CREATE EXTENSION IF NOT EXISTS unaccent;
  CREATE EXTENSION IF NOT EXISTS citext;
  CREATE EXTENSION IF NOT EXISTS pgcrypto;
SQL
