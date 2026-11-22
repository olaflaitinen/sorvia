-- V003: business rules as triggers, stored functions and procedures.
--
-- Rules enforced inside the database (not in application code) so that every
-- client, including ad hoc SQL sessions, obeys them:
--   R1  An expired batch can never be sold.                       SQLSTATE SV001
--   R2  A prescription-only drug needs a valid prescription
--       for the same customer with remaining quantity.            SQLSTATE SV002
--   R3  Stock can never go negative.                              SQLSTATE SV003
--   R4  Every stock change is written to the batch_movement ledger.
--   R5  Changes to master data are written to audit.change_log.
--
-- Custom SQLSTATE class "SV" is reserved for Sorvia business errors so that the
-- API can map them to precise HTTP responses.

SET search_path = pharma, public;

-- ---------------------------------------------------------------------------
-- Audit
-- ---------------------------------------------------------------------------

CREATE TABLE audit.change_log (
    change_id   bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name  text        NOT NULL,
    operation   text        NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    old_data    jsonb,
    new_data    jsonb,
    db_user     text        NOT NULL,
    app_user    text,
    changed_at  timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX change_log_table_time_idx ON audit.change_log (table_name, changed_at);

-- TG_ARGV holds column names that must never be copied into the log
-- (for example encrypted personal data).
CREATE FUNCTION audit.log_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, audit
AS $$
DECLARE
    v_old jsonb;
    v_new jsonb;
    i     integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN v_old := to_jsonb(OLD); END IF;
    IF TG_OP <> 'DELETE' THEN v_new := to_jsonb(NEW); END IF;
    IF TG_NARGS > 0 THEN
        FOR i IN 0 .. TG_NARGS - 1 LOOP
            v_old := v_old - TG_ARGV[i];
            v_new := v_new - TG_ARGV[i];
        END LOOP;
    END IF;
    INSERT INTO audit.change_log (table_name, operation, old_data, new_data, db_user, app_user)
    VALUES (TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, TG_OP, v_old, v_new, session_user,
            nullif(current_setting('sorvia.app_user', true), ''));
    RETURN NULL;
END
$$;

CREATE TRIGGER audit_branch AFTER INSERT OR UPDATE OR DELETE ON pharma.branch
    FOR EACH ROW EXECUTE FUNCTION audit.log_change();
CREATE TRIGGER audit_employee AFTER INSERT OR UPDATE OR DELETE ON pharma.employee
    FOR EACH ROW EXECUTE FUNCTION audit.log_change();
CREATE TRIGGER audit_drug AFTER INSERT OR UPDATE OR DELETE ON pharma.drug
    FOR EACH ROW EXECUTE FUNCTION audit.log_change();
CREATE TRIGGER audit_customer AFTER INSERT OR UPDATE OR DELETE ON pharma.customer
    FOR EACH ROW EXECUTE FUNCTION audit.log_change('fin_encrypted', 'fin_hash');
CREATE TRIGGER audit_prescription AFTER INSERT OR UPDATE OR DELETE ON pharma.prescription
    FOR EACH ROW EXECUTE FUNCTION audit.log_change();

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

-- Business dates are evaluated in Baku local time regardless of session TimeZone.
CREATE FUNCTION pharma.business_date(p_ts timestamptz)
RETURNS date
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT (p_ts AT TIME ZONE 'Asia/Baku')::date $$;

-- Loyalty tier: discount rate derived from accumulated bonus points.
CREATE FUNCTION pharma.customer_discount_rate(p_customer_id integer)
RETURNS numeric
LANGUAGE sql STABLE
AS $$
    SELECT CASE
               WHEN c.bonus_points >= 1000 THEN 0.10
               WHEN c.bonus_points >= 500  THEN 0.05
               WHEN c.bonus_points >= 100  THEN 0.02
               ELSE 0
           END
    FROM pharma.customer c
    WHERE c.customer_id = p_customer_id
$$;

-- ---------------------------------------------------------------------------
-- Sale line rules (R1, R2) and effects (R3, R4)
-- ---------------------------------------------------------------------------

CREATE FUNCTION pharma.sale_item_validate()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_drug_id     integer;
    v_expires_on  date;
    v_requires_rx boolean;
    v_price       numeric(10,2);
    v_customer_id integer;
    v_rx_id       integer;
    v_issued_on   date;
    v_valid_until date;
    v_rx_customer integer;
    v_day         date := pharma.business_date(NEW.sold_at);
BEGIN
    SELECT b.drug_id, b.expires_on, d.requires_prescription, d.unit_price
      INTO v_drug_id, v_expires_on, v_requires_rx, v_price
      FROM pharma.batch b
      JOIN pharma.drug d USING (drug_id)
     WHERE b.batch_id = NEW.batch_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Batch % does not exist', NEW.batch_id USING ERRCODE = 'foreign_key_violation';
    END IF;

    -- R1
    IF v_expires_on < v_day THEN
        RAISE EXCEPTION 'Batch % expired on %; it cannot be sold', NEW.batch_id, v_expires_on
            USING ERRCODE = 'SV001',
                  HINT = 'Run pharma.write_off_expired() to remove expired stock.';
    END IF;

    IF NEW.unit_price IS NULL THEN
        NEW.unit_price := v_price;
    END IF;

    -- R2
    IF v_requires_rx THEN
        SELECT s.customer_id, s.prescription_id
          INTO v_customer_id, v_rx_id
          FROM pharma.sale s
         WHERE s.sale_id = NEW.sale_id AND s.sold_at = NEW.sold_at;

        IF v_rx_id IS NULL THEN
            RAISE EXCEPTION 'Drug % requires a prescription', v_drug_id USING ERRCODE = 'SV002';
        END IF;

        SELECT p.customer_id, p.issued_on, p.valid_until
          INTO v_rx_customer, v_issued_on, v_valid_until
          FROM pharma.prescription p
         WHERE p.prescription_id = v_rx_id;

        IF v_rx_customer IS DISTINCT FROM v_customer_id THEN
            RAISE EXCEPTION 'Prescription % belongs to another customer', v_rx_id USING ERRCODE = 'SV002';
        END IF;
        IF v_day NOT BETWEEN v_issued_on AND v_valid_until THEN
            RAISE EXCEPTION 'Prescription % is not valid on %', v_rx_id, v_day USING ERRCODE = 'SV002';
        END IF;

        UPDATE pharma.prescription_item pi
           SET dispensed_quantity = pi.dispensed_quantity + NEW.quantity
         WHERE pi.prescription_id = v_rx_id
           AND pi.drug_id = v_drug_id
           AND pi.dispensed_quantity + NEW.quantity <= pi.quantity;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Prescription % does not cover % unit(s) of drug %', v_rx_id, NEW.quantity, v_drug_id
                USING ERRCODE = 'SV002';
        END IF;
    END IF;

    RETURN NEW;
END
$$;

CREATE FUNCTION pharma.sale_item_apply()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_branch_id smallint;
BEGIN
    SELECT s.branch_id INTO v_branch_id
      FROM pharma.sale s
     WHERE s.sale_id = NEW.sale_id AND s.sold_at = NEW.sold_at;

    -- R3: conditional update is atomic; no read-then-write race.
    UPDATE pharma.stock st
       SET quantity = st.quantity - NEW.quantity
     WHERE st.branch_id = v_branch_id
       AND st.batch_id = NEW.batch_id
       AND st.quantity >= NEW.quantity;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Insufficient stock of batch % in branch %', NEW.batch_id, v_branch_id
            USING ERRCODE = 'SV003';
    END IF;

    -- R4
    INSERT INTO pharma.batch_movement (batch_id, branch_id, quantity_delta, reason, reference_id, occurred_at)
    VALUES (NEW.batch_id, v_branch_id, -NEW.quantity, 'sale', NEW.sale_id, NEW.sold_at);

    UPDATE pharma.sale s
       SET gross_amount = s.gross_amount + NEW.quantity * NEW.unit_price
     WHERE s.sale_id = NEW.sale_id AND s.sold_at = NEW.sold_at;

    RETURN NULL;
END
$$;

CREATE TRIGGER sale_item_validate BEFORE INSERT ON pharma.sale_item
    FOR EACH ROW EXECUTE FUNCTION pharma.sale_item_validate();
CREATE TRIGGER sale_item_apply AFTER INSERT ON pharma.sale_item
    FOR EACH ROW EXECUTE FUNCTION pharma.sale_item_apply();

-- Sale lines are immutable; corrections are new documents.
CREATE FUNCTION pharma.reject_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% on %.% is not allowed; ledger rows are immutable',
        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = 'SV005';
END
$$;

CREATE TRIGGER sale_item_immutable BEFORE UPDATE ON pharma.sale_item
    FOR EACH ROW EXECUTE FUNCTION pharma.reject_change();
CREATE TRIGGER batch_movement_immutable BEFORE UPDATE OR DELETE ON pharma.batch_movement
    FOR EACH ROW EXECUTE FUNCTION pharma.reject_change();

-- ---------------------------------------------------------------------------
-- Stock transfer between branches
-- ---------------------------------------------------------------------------

CREATE FUNCTION pharma.stock_transfer_apply()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- Lock both stock rows in a global order (branch_id ascending) so that two
    -- opposite transfers can never deadlock.
    PERFORM 1
       FROM pharma.stock st
      WHERE st.batch_id = NEW.batch_id
        AND st.branch_id IN (NEW.from_branch_id, NEW.to_branch_id)
      ORDER BY st.branch_id
        FOR UPDATE;

    UPDATE pharma.stock st
       SET quantity = st.quantity - NEW.quantity
     WHERE st.branch_id = NEW.from_branch_id
       AND st.batch_id = NEW.batch_id
       AND st.quantity >= NEW.quantity;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Insufficient stock of batch % in branch % for transfer',
            NEW.batch_id, NEW.from_branch_id USING ERRCODE = 'SV003';
    END IF;

    INSERT INTO pharma.stock AS st (branch_id, batch_id, quantity)
    VALUES (NEW.to_branch_id, NEW.batch_id, NEW.quantity)
    ON CONFLICT (branch_id, batch_id) DO UPDATE SET quantity = st.quantity + EXCLUDED.quantity;

    INSERT INTO pharma.batch_movement (batch_id, branch_id, quantity_delta, reason, reference_id, occurred_at)
    VALUES (NEW.batch_id, NEW.from_branch_id, -NEW.quantity, 'transfer_out', NEW.transfer_id, NEW.transferred_at),
           (NEW.batch_id, NEW.to_branch_id,    NEW.quantity, 'transfer_in',  NEW.transfer_id, NEW.transferred_at);

    RETURN NULL;
END
$$;

CREATE TRIGGER stock_transfer_apply AFTER INSERT ON pharma.stock_transfer
    FOR EACH ROW EXECUTE FUNCTION pharma.stock_transfer_apply();

-- ---------------------------------------------------------------------------
-- Public procedures and functions (the API calls only these)
-- ---------------------------------------------------------------------------

CREATE PROCEDURE pharma.receive_batch(p_branch_id smallint, p_batch_id integer, p_quantity integer,
                                      p_received_at timestamptz DEFAULT now())
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_quantity <= 0 THEN
        RAISE EXCEPTION 'Quantity must be positive' USING ERRCODE = 'check_violation';
    END IF;

    INSERT INTO pharma.stock AS st (branch_id, batch_id, quantity)
    VALUES (p_branch_id, p_batch_id, p_quantity)
    ON CONFLICT (branch_id, batch_id) DO UPDATE SET quantity = st.quantity + EXCLUDED.quantity;

    INSERT INTO pharma.batch_movement (batch_id, branch_id, quantity_delta, reason, occurred_at)
    VALUES (p_batch_id, p_branch_id, p_quantity, 'receipt', p_received_at);
END
$$;

CREATE PROCEDURE pharma.transfer_stock(p_from_branch_id smallint, p_to_branch_id smallint,
                                       p_batch_id integer, p_quantity integer, p_employee_id integer)
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pharma.employee e
                    WHERE e.employee_id = p_employee_id
                      AND e.branch_id = p_from_branch_id
                      AND e.is_active) THEN
        RAISE EXCEPTION 'Employee % is not an active member of branch %', p_employee_id, p_from_branch_id
            USING ERRCODE = 'SV004';
    END IF;

    INSERT INTO pharma.stock_transfer (from_branch_id, to_branch_id, batch_id, quantity, employee_id)
    VALUES (p_from_branch_id, p_to_branch_id, p_batch_id, p_quantity, p_employee_id);
END
$$;

-- Registers a complete sale atomically.
--   p_items: [{"drug_id": 12, "quantity": 2}, ...]
-- Batches are allocated FEFO (first expiring, first out) among non-expired
-- batches of the branch. Returns the new sale_id.
CREATE FUNCTION pharma.register_sale(
    p_branch_id       smallint,
    p_employee_id     integer,
    p_items           jsonb,
    p_customer_id     integer     DEFAULT NULL,
    p_prescription_id integer     DEFAULT NULL,
    p_sold_at         timestamptz DEFAULT now()
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_sale_id   bigint;
    v_line_no   smallint := 0;
    v_item      jsonb;
    v_drug_id   integer;
    v_remaining integer;
    v_take      integer;
    v_alloc     record;
    v_gross     numeric(12,2);
    v_rate      numeric;
    v_day       date := pharma.business_date(p_sold_at);
BEGIN
    IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'p_items must be a non-empty JSON array' USING ERRCODE = 'invalid_parameter_value';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pharma.employee e
                    WHERE e.employee_id = p_employee_id
                      AND e.branch_id = p_branch_id
                      AND e.is_active) THEN
        RAISE EXCEPTION 'Employee % is not an active member of branch %', p_employee_id, p_branch_id
            USING ERRCODE = 'SV004';
    END IF;

    INSERT INTO pharma.sale (sold_at, branch_id, employee_id, customer_id, prescription_id)
    VALUES (p_sold_at, p_branch_id, p_employee_id, p_customer_id, p_prescription_id)
    RETURNING sale_id INTO v_sale_id;

    FOR v_item IN SELECT * FROM jsonb_array_elements(p_items) LOOP
        v_drug_id   := (v_item ->> 'drug_id')::integer;
        v_remaining := (v_item ->> 'quantity')::integer;

        IF v_drug_id IS NULL OR v_remaining IS NULL OR v_remaining <= 0 THEN
            RAISE EXCEPTION 'Invalid item %', v_item USING ERRCODE = 'invalid_parameter_value';
        END IF;

        FOR v_alloc IN
            SELECT st.batch_id, st.quantity
              FROM pharma.stock st
              JOIN pharma.batch b USING (batch_id)
             WHERE st.branch_id = p_branch_id
               AND b.drug_id = v_drug_id
               AND b.expires_on >= v_day
               AND st.quantity > 0
             ORDER BY b.expires_on, b.batch_id
               FOR UPDATE OF st
        LOOP
            EXIT WHEN v_remaining = 0;
            v_take    := least(v_remaining, v_alloc.quantity);
            v_line_no := v_line_no + 1;
            INSERT INTO pharma.sale_item (sale_id, sold_at, line_no, batch_id, quantity)
            VALUES (v_sale_id, p_sold_at, v_line_no, v_alloc.batch_id, v_take);
            v_remaining := v_remaining - v_take;
        END LOOP;

        IF v_remaining > 0 THEN
            RAISE EXCEPTION 'Insufficient stock of drug % in branch % (% unit(s) missing)',
                v_drug_id, p_branch_id, v_remaining USING ERRCODE = 'SV003';
        END IF;
    END LOOP;

    IF p_customer_id IS NOT NULL THEN
        SELECT s.gross_amount INTO v_gross FROM pharma.sale s
         WHERE s.sale_id = v_sale_id AND s.sold_at = p_sold_at;
        v_rate := coalesce(pharma.customer_discount_rate(p_customer_id), 0);

        UPDATE pharma.sale s
           SET discount_amount = round(v_gross * v_rate, 2)
         WHERE s.sale_id = v_sale_id AND s.sold_at = p_sold_at;

        -- One bonus point per 10 AZN paid.
        UPDATE pharma.customer c
           SET bonus_points = c.bonus_points + floor((v_gross - round(v_gross * v_rate, 2)) / 10)::integer
         WHERE c.customer_id = p_customer_id;
    END IF;

    RETURN v_sale_id;
END
$$;

-- Removes expired stock and records write-off movements. Returns affected rows.
CREATE FUNCTION pharma.write_off_expired(p_as_of date DEFAULT current_date)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_count integer;
BEGIN
    WITH expired AS (
        SELECT st.branch_id, st.batch_id, st.quantity
          FROM pharma.stock st
          JOIN pharma.batch b USING (batch_id)
         WHERE b.expires_on < p_as_of
           AND st.quantity > 0
           FOR UPDATE OF st
    ), ledger AS (
        INSERT INTO pharma.batch_movement (batch_id, branch_id, quantity_delta, reason)
        SELECT batch_id, branch_id, -quantity, 'write_off' FROM expired
    )
    UPDATE pharma.stock st
       SET quantity = 0
      FROM expired e
     WHERE st.branch_id = e.branch_id AND st.batch_id = e.batch_id;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$$;

-- Temporal traceability: where was a batch, and how much of it, at time p_at?
CREATE FUNCTION pharma.batch_location_at(p_batch_id integer, p_at timestamptz)
RETURNS TABLE (branch_id smallint, quantity bigint)
LANGUAGE sql STABLE
AS $$
    SELECT m.branch_id, sum(m.quantity_delta) AS quantity
      FROM pharma.batch_movement m
     WHERE m.batch_id = p_batch_id
       AND m.occurred_at <= p_at
     GROUP BY m.branch_id
    HAVING sum(m.quantity_delta) > 0
     ORDER BY m.branch_id
$$;
