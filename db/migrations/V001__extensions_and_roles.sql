-- V001: extensions, schemas and group roles.
--
-- Group roles are NOLOGIN. Login roles are created by `sorvia bootstrap-roles`
-- so that passwords never live in version control.
--
--   sorvia_app     API service role. Writes platform tables, calls domain procedures.
--   sorvia_reader  Executes natural-language generated SQL. SELECT only, RLS enforced.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS hypopg;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sorvia_app') THEN
        CREATE ROLE sorvia_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sorvia_reader') THEN
        CREATE ROLE sorvia_reader NOLOGIN;
    END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS pharma;     -- OLTP domain: pharmacy network
CREATE SCHEMA IF NOT EXISTS audit;      -- change history
CREATE SCHEMA IF NOT EXISTS sorvia;     -- platform: users, query log, semantic layer
CREATE SCHEMA IF NOT EXISTS analytics;  -- OLAP star schema

-- Nobody gets anything implicitly.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA pharma, audit, sorvia, analytics FROM PUBLIC;
