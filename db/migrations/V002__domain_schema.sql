-- V002: OLTP domain schema for a multi-branch pharmacy network.
--
-- Design notes
--   * Normalised to 3NF; every non-key attribute depends on the key, the whole key
--     and nothing but the key. See docs/database-design.md for the derivation.
--   * Money is numeric(12,2); never float.
--   * Natural keys are protected with UNIQUE constraints, surrogate keys are
--     identity columns.
--   * pharma.sale is range partitioned by month on sold_at (RQ3).

SET search_path = pharma, public;

CREATE TYPE pharma.movement_reason AS ENUM (
    'receipt', 'sale', 'transfer_in', 'transfer_out', 'write_off', 'adjustment'
);

CREATE TABLE pharma.branch (
    branch_id   smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        text        NOT NULL UNIQUE CHECK (code ~ '^[A-Z]{3}[0-9]{2}$'),
    name        text        NOT NULL,
    city        text        NOT NULL,
    address     text        NOT NULL,
    phone       text        CHECK (phone ~ '^\+994[0-9]{9}$'),
    opened_on   date        NOT NULL
);

CREATE TABLE pharma.job_position (
    position_id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text NOT NULL UNIQUE
);

CREATE TABLE pharma.employee (
    employee_id integer  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id   smallint NOT NULL REFERENCES pharma.branch,
    position_id smallint NOT NULL REFERENCES pharma.job_position,
    first_name  text     NOT NULL,
    last_name   text     NOT NULL,
    hired_on    date     NOT NULL,
    salary      numeric(10,2) NOT NULL CHECK (salary > 0),
    is_active   boolean  NOT NULL DEFAULT true
);

CREATE TABLE pharma.manufacturer (
    manufacturer_id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text NOT NULL UNIQUE,
    country         text NOT NULL
);

CREATE TABLE pharma.category (
    category_id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text     NOT NULL UNIQUE,
    parent_id   smallint REFERENCES pharma.category
);

CREATE TABLE pharma.drug (
    drug_id               integer  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_name            text     NOT NULL,
    active_ingredient     text     NOT NULL,
    category_id           smallint NOT NULL REFERENCES pharma.category,
    manufacturer_id       smallint NOT NULL REFERENCES pharma.manufacturer,
    dosage_form           text     NOT NULL CHECK (dosage_form IN
                              ('tablet', 'capsule', 'syrup', 'injection', 'ointment', 'drops', 'spray', 'powder')),
    strength              text     NOT NULL,
    requires_prescription boolean  NOT NULL DEFAULT false,
    unit_price            numeric(10,2) NOT NULL CHECK (unit_price > 0),
    min_stock             integer  NOT NULL DEFAULT 20 CHECK (min_stock >= 0),
    UNIQUE (trade_name, strength, dosage_form)
);

CREATE TABLE pharma.batch (
    batch_id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    drug_id         integer NOT NULL REFERENCES pharma.drug,
    lot_number      text    NOT NULL,
    manufactured_on date    NOT NULL,
    expires_on      date    NOT NULL,
    UNIQUE (drug_id, lot_number),
    CHECK (expires_on > manufactured_on)
);

CREATE TABLE pharma.stock (
    branch_id smallint NOT NULL REFERENCES pharma.branch,
    batch_id  integer  NOT NULL REFERENCES pharma.batch,
    quantity  integer  NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY (branch_id, batch_id)
);

-- Personal data: the FIN (national ID) is stored encrypted (pgp_sym_encrypt)
-- and as a keyed hash for equality lookups. Neither column is readable by
-- sorvia_reader (column-level privileges, V006).
CREATE TABLE pharma.customer (
    customer_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    first_name    text    NOT NULL,
    last_name     text    NOT NULL,
    fin_encrypted bytea,
    fin_hash      text    UNIQUE,
    phone         text    CHECK (phone ~ '^\+994[0-9]{9}$'),
    birth_year    smallint CHECK (birth_year BETWEEN 1900 AND 2100),
    gender        char(1) CHECK (gender IN ('M', 'F')),
    city          text,
    bonus_points  integer NOT NULL DEFAULT 0 CHECK (bonus_points >= 0),
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pharma.doctor (
    doctor_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    first_name  text NOT NULL,
    last_name   text NOT NULL,
    clinic      text NOT NULL,
    specialty   text NOT NULL,
    license_no  text NOT NULL UNIQUE
);

CREATE TABLE pharma.prescription (
    prescription_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id     integer NOT NULL REFERENCES pharma.customer,
    doctor_id       integer NOT NULL REFERENCES pharma.doctor,
    issued_on       date    NOT NULL,
    valid_until     date    NOT NULL,
    CHECK (valid_until >= issued_on)
);

CREATE TABLE pharma.prescription_item (
    prescription_id    integer NOT NULL REFERENCES pharma.prescription ON DELETE CASCADE,
    drug_id            integer NOT NULL REFERENCES pharma.drug,
    quantity           integer NOT NULL CHECK (quantity > 0),
    dispensed_quantity integer NOT NULL DEFAULT 0,
    PRIMARY KEY (prescription_id, drug_id),
    CHECK (dispensed_quantity BETWEEN 0 AND quantity)
);

-- Sales header, partitioned by month. The partition key must be part of the PK.
CREATE TABLE pharma.sale (
    sale_id         bigint      GENERATED ALWAYS AS IDENTITY,
    sold_at         timestamptz NOT NULL,
    branch_id       smallint    NOT NULL REFERENCES pharma.branch,
    employee_id     integer     NOT NULL REFERENCES pharma.employee,
    customer_id     integer     REFERENCES pharma.customer,
    prescription_id integer     REFERENCES pharma.prescription,
    gross_amount    numeric(12,2) NOT NULL DEFAULT 0 CHECK (gross_amount >= 0),
    discount_amount numeric(12,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    net_amount      numeric(12,2) GENERATED ALWAYS AS (gross_amount - discount_amount) STORED,
    PRIMARY KEY (sale_id, sold_at),
    CHECK (discount_amount <= gross_amount)
) PARTITION BY RANGE (sold_at);

CREATE TABLE pharma.sale_default PARTITION OF pharma.sale DEFAULT;

CREATE TABLE pharma.sale_item (
    sale_id    bigint      NOT NULL,
    sold_at    timestamptz NOT NULL,
    line_no    smallint    NOT NULL CHECK (line_no > 0),
    batch_id   integer     NOT NULL REFERENCES pharma.batch,
    quantity   integer     NOT NULL CHECK (quantity > 0),
    unit_price numeric(10,2) NOT NULL CHECK (unit_price > 0),
    PRIMARY KEY (sale_id, sold_at, line_no),
    FOREIGN KEY (sale_id, sold_at) REFERENCES pharma.sale (sale_id, sold_at) ON DELETE CASCADE
);

CREATE TABLE pharma.stock_transfer (
    transfer_id    integer     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_branch_id smallint    NOT NULL REFERENCES pharma.branch,
    to_branch_id   smallint    NOT NULL REFERENCES pharma.branch,
    batch_id       integer     NOT NULL REFERENCES pharma.batch,
    quantity       integer     NOT NULL CHECK (quantity > 0),
    employee_id    integer     NOT NULL REFERENCES pharma.employee,
    transferred_at timestamptz NOT NULL DEFAULT now(),
    CHECK (from_branch_id <> to_branch_id)
);

-- Append-only ledger of every stock change. It is the source of truth for
-- temporal traceability: "where was batch X on date D?" (pharma.batch_location_at).
CREATE TABLE pharma.batch_movement (
    movement_id    bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id       integer     NOT NULL REFERENCES pharma.batch,
    branch_id      smallint    NOT NULL REFERENCES pharma.branch,
    quantity_delta integer     NOT NULL CHECK (quantity_delta <> 0),
    reason         pharma.movement_reason NOT NULL,
    reference_id   bigint,
    occurred_at    timestamptz NOT NULL DEFAULT now()
);

-- Indexes on foreign keys and hot predicates. Additional indexes are proposed
-- by the Sorvia index advisor from the observed workload.
CREATE INDEX employee_branch_idx       ON pharma.employee (branch_id);
CREATE INDEX drug_category_idx         ON pharma.drug (category_id);
CREATE INDEX drug_manufacturer_idx     ON pharma.drug (manufacturer_id);
CREATE INDEX batch_drug_expiry_idx     ON pharma.batch (drug_id, expires_on);
CREATE INDEX stock_batch_idx           ON pharma.stock (batch_id);
CREATE INDEX prescription_customer_idx ON pharma.prescription (customer_id);
CREATE INDEX sale_branch_time_idx      ON pharma.sale (branch_id, sold_at);
CREATE INDEX sale_customer_idx         ON pharma.sale (customer_id) WHERE customer_id IS NOT NULL;
CREATE INDEX sale_item_batch_idx       ON pharma.sale_item (batch_id);
CREATE INDEX movement_batch_time_idx   ON pharma.batch_movement (batch_id, occurred_at);
CREATE INDEX movement_time_brin        ON pharma.batch_movement USING brin (occurred_at);

-- Monthly partition management.
CREATE FUNCTION pharma.ensure_sale_partitions(p_from date, p_to date)
RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    m       date := date_trunc('month', p_from)::date;
    created integer := 0;
    part    text;
BEGIN
    WHILE m <= p_to LOOP
        part := format('sale_%s', to_char(m, 'YYYY_MM'));
        IF to_regclass('pharma.' || part) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE pharma.%I PARTITION OF pharma.sale FOR VALUES FROM (%L) TO (%L)',
                part, m, (m + interval '1 month')::date);
            created := created + 1;
        END IF;
        m := (m + interval '1 month')::date;
    END LOOP;
    RETURN created;
END
$$;

SELECT pharma.ensure_sale_partitions(date '2024-01-01', date '2027-12-01');
