-- V009: portability for managed PostgreSQL services.
--
-- Supabase installs some extensions (pgcrypto, pg_stat_statements, ...) into
-- a dedicated "extensions" schema. The application roles need USAGE on it to
-- resolve the vector type and its operators. On plain PostgreSQL the schema
-- does not exist and this migration does nothing.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'extensions') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA extensions TO sorvia_app, sorvia_reader';
    END IF;
END
$$;
