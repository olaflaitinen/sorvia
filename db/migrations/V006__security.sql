-- V006: privileges, Row-Level Security and the capability-ticket protocol.
--
-- Threat model
--   SQL produced by a language model is untrusted input. Sorvia therefore does
--   not rely on the prompt or on the application to keep a pharmacist inside
--   their own branch. The database enforces it:
--
--   1. The API (role sorvia_app) asks for a one-time ticket that encodes the
--      caller's scope:        SELECT sorvia.issue_scope_ticket(user_id)
--   2. The reader connection (role sorvia_reader) redeems it inside the same
--      transaction that runs the generated SQL:
--                             SELECT sorvia.redeem_scope_ticket(ticket)
--      Redeeming binds the scope to (backend pid, transaction id).
--   3. RLS policies read the scope through SECURITY DEFINER functions.
--      A different transaction, or a session that never redeemed a ticket,
--      sees no branch-scoped rows at all (deny by default).
--
--   The reader role can neither read nor write sorvia.session_scope or
--   sorvia.scope_ticket, so generated SQL cannot forge or widen its scope.

-- ---------------------------------------------------------------------------
-- Scope protocol
-- ---------------------------------------------------------------------------

CREATE FUNCTION sorvia.issue_scope_ticket(p_user_id integer)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, sorvia
AS $$
DECLARE
    v_user   sorvia.app_user;
    v_ticket uuid;
BEGIN
    SELECT * INTO v_user FROM sorvia.app_user WHERE user_id = p_user_id AND is_active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown or inactive user %', p_user_id USING ERRCODE = 'insufficient_privilege';
    END IF;

    DELETE FROM sorvia.scope_ticket WHERE expires_at < clock_timestamp();

    INSERT INTO sorvia.scope_ticket (user_id, branch_id, all_branches)
    VALUES (v_user.user_id,
            v_user.branch_id,
            v_user.role IN ('admin', 'manager') AND v_user.branch_id IS NULL)
    RETURNING ticket INTO v_ticket;

    RETURN v_ticket;
END
$$;

CREATE FUNCTION sorvia.redeem_scope_ticket(p_ticket uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, sorvia
AS $$
DECLARE
    v_t sorvia.scope_ticket;
BEGIN
    DELETE FROM sorvia.scope_ticket
     WHERE ticket = p_ticket AND expires_at >= clock_timestamp()
    RETURNING * INTO v_t;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Invalid or expired scope ticket' USING ERRCODE = 'insufficient_privilege';
    END IF;

    INSERT INTO sorvia.session_scope (backend_pid, xact_id, user_id, branch_id, all_branches)
    VALUES (pg_backend_pid(), pg_current_xact_id(), v_t.user_id, v_t.branch_id, v_t.all_branches)
    ON CONFLICT (backend_pid) DO UPDATE
        SET xact_id = EXCLUDED.xact_id,
            user_id = EXCLUDED.user_id,
            branch_id = EXCLUDED.branch_id,
            all_branches = EXCLUDED.all_branches;
END
$$;

CREATE FUNCTION sorvia.scope_branch_id()
RETURNS smallint
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = pg_catalog, sorvia
AS $$
    SELECT s.branch_id
      FROM sorvia.session_scope s
     WHERE s.backend_pid = pg_backend_pid()
       AND s.xact_id = pg_current_xact_id_if_assigned()
$$;

CREATE FUNCTION sorvia.scope_all_branches()
RETURNS boolean
LANGUAGE sql STABLE
SECURITY DEFINER
SET search_path = pg_catalog, sorvia
AS $$
    SELECT coalesce(
        (SELECT s.all_branches
           FROM sorvia.session_scope s
          WHERE s.backend_pid = pg_backend_pid()
            AND s.xact_id = pg_current_xact_id_if_assigned()),
        false)
$$;

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------
-- Scope functions are wrapped in scalar sub-selects so that the planner
-- evaluates them once per query (InitPlan) instead of once per row.

ALTER TABLE pharma.employee       ENABLE ROW LEVEL SECURITY;
ALTER TABLE pharma.stock          ENABLE ROW LEVEL SECURITY;
ALTER TABLE pharma.sale           ENABLE ROW LEVEL SECURITY;
ALTER TABLE pharma.sale_item      ENABLE ROW LEVEL SECURITY;
ALTER TABLE pharma.stock_transfer ENABLE ROW LEVEL SECURITY;
ALTER TABLE pharma.batch_movement ENABLE ROW LEVEL SECURITY;

CREATE POLICY reader_scope ON pharma.employee FOR SELECT TO sorvia_reader
    USING ((SELECT sorvia.scope_all_branches()) OR branch_id = (SELECT sorvia.scope_branch_id()));
CREATE POLICY reader_scope ON pharma.stock FOR SELECT TO sorvia_reader
    USING ((SELECT sorvia.scope_all_branches()) OR branch_id = (SELECT sorvia.scope_branch_id()));
CREATE POLICY reader_scope ON pharma.sale FOR SELECT TO sorvia_reader
    USING ((SELECT sorvia.scope_all_branches()) OR branch_id = (SELECT sorvia.scope_branch_id()));
CREATE POLICY reader_scope ON pharma.batch_movement FOR SELECT TO sorvia_reader
    USING ((SELECT sorvia.scope_all_branches()) OR branch_id = (SELECT sorvia.scope_branch_id()));
CREATE POLICY reader_scope ON pharma.stock_transfer FOR SELECT TO sorvia_reader
    USING ((SELECT sorvia.scope_all_branches())
           OR (SELECT sorvia.scope_branch_id()) IN (from_branch_id, to_branch_id));
-- A sale line is visible when its header is visible; the inner query on
-- pharma.sale is itself filtered by the policy above.
CREATE POLICY reader_scope ON pharma.sale_item FOR SELECT TO sorvia_reader
    USING ((SELECT sorvia.scope_all_branches())
           OR EXISTS (SELECT 1 FROM pharma.sale s
                       WHERE s.sale_id = sale_item.sale_id AND s.sold_at = sale_item.sold_at));

-- The application role works on behalf of authenticated users and is trusted.
CREATE POLICY app_all ON pharma.employee       TO sorvia_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON pharma.stock          TO sorvia_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON pharma.sale           TO sorvia_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON pharma.sale_item      TO sorvia_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON pharma.stock_transfer TO sorvia_app USING (true) WITH CHECK (true);
CREATE POLICY app_all ON pharma.batch_movement TO sorvia_app USING (true) WITH CHECK (true);

-- ---------------------------------------------------------------------------
-- Privileges
-- ---------------------------------------------------------------------------
-- PostgreSQL grants EXECUTE on new functions to PUBLIC by default. Revoke it
-- everywhere and grant back only what each role needs.

REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA pharma, sorvia, audit FROM PUBLIC;
REVOKE EXECUTE ON ALL PROCEDURES IN SCHEMA pharma FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA pharma, sorvia, audit, analytics REVOKE EXECUTE ON ROUTINES FROM PUBLIC;

-- sorvia_reader: read-only access to the domain and analytics, nothing else.
GRANT USAGE ON SCHEMA pharma, analytics, sorvia TO sorvia_reader;
GRANT SELECT ON pharma.branch, pharma.job_position, pharma.employee, pharma.manufacturer,
                pharma.category, pharma.drug, pharma.batch, pharma.stock, pharma.doctor,
                pharma.prescription, pharma.prescription_item, pharma.sale, pharma.sale_item,
                pharma.stock_transfer, pharma.batch_movement,
                pharma.v_drug_catalog, pharma.v_sale_lines, pharma.v_stock_by_drug,
                pharma.v_low_stock, pharma.v_expiring_soon, pharma.v_branch_monthly_revenue
             TO sorvia_reader;
-- Column-level privilege: personal identifiers are not readable.
GRANT SELECT (customer_id, first_name, last_name, phone, birth_year, gender, city, bonus_points, created_at)
    ON pharma.customer TO sorvia_reader;
GRANT EXECUTE ON FUNCTION pharma.business_date(timestamptz),
                          pharma.customer_discount_rate(integer),
                          pharma.batch_location_at(integer, timestamptz),
                          sorvia.redeem_scope_ticket(uuid),
                          sorvia.scope_branch_id(),
                          sorvia.scope_all_branches()
             TO sorvia_reader;

-- sorvia_app: the API service.
GRANT USAGE ON SCHEMA public, pharma, audit, sorvia, analytics TO sorvia_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA pharma TO sorvia_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA pharma, sorvia TO sorvia_app;
GRANT SELECT ON audit.change_log TO sorvia_app;
GRANT SELECT, INSERT, UPDATE ON sorvia.app_user, sorvia.nl_query, sorvia.query_feedback,
                                sorvia.index_recommendation TO sorvia_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON sorvia.schema_doc TO sorvia_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pharma TO sorvia_app;
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA pharma TO sorvia_app;
GRANT EXECUTE ON FUNCTION sorvia.issue_scope_ticket(integer),
                          sorvia.scope_branch_id(),
                          sorvia.scope_all_branches()
             TO sorvia_app;
