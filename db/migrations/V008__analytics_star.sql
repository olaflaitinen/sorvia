-- V008: analytical star schema (Kimball dimensional model).
--
-- Grain of analytics.fact_sales: one row per sale line.
-- The header-level discount is allocated to lines in proportion to their gross
-- amount so that facts stay additive across every dimension.

SET search_path = analytics, public;

CREATE TABLE analytics.dim_date (
    date_key     integer  PRIMARY KEY,          -- yyyymmdd
    full_date    date     NOT NULL UNIQUE,
    year         smallint NOT NULL,
    quarter      smallint NOT NULL,
    month        smallint NOT NULL,
    month_name   text     NOT NULL,
    day_of_week  smallint NOT NULL,              -- ISO: 1 = Monday
    day_name     text     NOT NULL,
    is_weekend   boolean  NOT NULL
);

CREATE TABLE analytics.dim_branch (
    branch_key  smallint PRIMARY KEY,
    code        text NOT NULL,
    name        text NOT NULL,
    city        text NOT NULL
);

CREATE TABLE analytics.dim_drug (
    drug_key              integer PRIMARY KEY,
    trade_name            text    NOT NULL,
    active_ingredient     text    NOT NULL,
    category_name         text    NOT NULL,
    manufacturer_name     text    NOT NULL,
    manufacturer_country  text    NOT NULL,
    dosage_form           text    NOT NULL,
    requires_prescription boolean NOT NULL
);

-- customer_key = 0 represents anonymous (walk-in) customers.
CREATE TABLE analytics.dim_customer (
    customer_key integer PRIMARY KEY,
    age_group    text NOT NULL,
    gender       text NOT NULL,
    city         text NOT NULL
);

CREATE TABLE analytics.fact_sales (
    sale_id         bigint   NOT NULL,
    line_no         smallint NOT NULL,
    date_key        integer  NOT NULL REFERENCES analytics.dim_date,
    branch_key      smallint NOT NULL REFERENCES analytics.dim_branch,
    drug_key        integer  NOT NULL REFERENCES analytics.dim_drug,
    customer_key    integer  NOT NULL REFERENCES analytics.dim_customer,
    quantity        integer  NOT NULL,
    gross_amount    numeric(12,2) NOT NULL,
    discount_amount numeric(12,2) NOT NULL,
    net_amount      numeric(12,2) NOT NULL,
    PRIMARY KEY (sale_id, line_no)
);

CREATE INDEX fact_sales_date_idx   ON analytics.fact_sales (date_key);
CREATE INDEX fact_sales_branch_idx ON analytics.fact_sales (branch_key, date_key);
CREATE INDEX fact_sales_drug_idx   ON analytics.fact_sales (drug_key);

CREATE TABLE analytics.etl_state (
    singleton    boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    last_sale_ts timestamptz NOT NULL DEFAULT '-infinity',
    refreshed_at timestamptz
);
INSERT INTO analytics.etl_state DEFAULT VALUES;

-- Populate the date dimension for the supported range.
INSERT INTO analytics.dim_date
SELECT to_char(d, 'YYYYMMDD')::integer,
       d::date,
       extract(year FROM d)::smallint,
       extract(quarter FROM d)::smallint,
       extract(month FROM d)::smallint,
       (ARRAY['Yanvar','Fevral','Mart','Aprel','May','İyun','İyul','Avqust','Sentyabr','Oktyabr','Noyabr','Dekabr'])
           [extract(month FROM d)::integer],
       extract(isodow FROM d)::smallint,
       (ARRAY['Bazar ertəsi','Çərşənbə axşamı','Çərşənbə','Cümə axşamı','Cümə','Şənbə','Bazar'])
           [extract(isodow FROM d)::integer],
       extract(isodow FROM d) IN (6, 7)
  FROM generate_series(date '2023-01-01', date '2030-12-31', interval '1 day') AS d;

-- Incremental ETL. p_full => rebuild facts from scratch.
CREATE PROCEDURE analytics.refresh(p_full boolean DEFAULT false)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, analytics, pharma
AS $$
DECLARE
    v_from timestamptz;
    v_to   timestamptz;
BEGIN
    INSERT INTO analytics.dim_branch AS t (branch_key, code, name, city)
    SELECT branch_id, code, name, city FROM pharma.branch
    ON CONFLICT (branch_key) DO UPDATE
       SET code = EXCLUDED.code, name = EXCLUDED.name, city = EXCLUDED.city;

    INSERT INTO analytics.dim_drug AS t
    SELECT d.drug_id, d.trade_name, d.active_ingredient, c.name, m.name, m.country,
           d.dosage_form, d.requires_prescription
      FROM pharma.drug d
      JOIN pharma.category c USING (category_id)
      JOIN pharma.manufacturer m USING (manufacturer_id)
    ON CONFLICT (drug_key) DO UPDATE
       SET trade_name = EXCLUDED.trade_name, active_ingredient = EXCLUDED.active_ingredient,
           category_name = EXCLUDED.category_name, manufacturer_name = EXCLUDED.manufacturer_name,
           manufacturer_country = EXCLUDED.manufacturer_country, dosage_form = EXCLUDED.dosage_form,
           requires_prescription = EXCLUDED.requires_prescription;

    INSERT INTO analytics.dim_customer VALUES (0, 'naməlum', 'naməlum', 'naməlum')
    ON CONFLICT (customer_key) DO NOTHING;

    INSERT INTO analytics.dim_customer AS t
    SELECT c.customer_id,
           CASE
               WHEN c.birth_year IS NULL THEN 'naməlum'
               WHEN extract(year FROM current_date) - c.birth_year < 25 THEN '18-24'
               WHEN extract(year FROM current_date) - c.birth_year < 35 THEN '25-34'
               WHEN extract(year FROM current_date) - c.birth_year < 50 THEN '35-49'
               WHEN extract(year FROM current_date) - c.birth_year < 65 THEN '50-64'
               ELSE '65+'
           END,
           coalesce(c.gender::text, 'naməlum'),
           coalesce(c.city, 'naməlum')
      FROM pharma.customer c
    ON CONFLICT (customer_key) DO UPDATE
       SET age_group = EXCLUDED.age_group, gender = EXCLUDED.gender, city = EXCLUDED.city;

    IF p_full THEN
        TRUNCATE analytics.fact_sales;
        v_from := '-infinity';
    ELSE
        SELECT last_sale_ts INTO v_from FROM analytics.etl_state;
    END IF;

    -- Leave a safety margin for transactions that have not committed yet.
    v_to := now() - interval '1 minute';

    INSERT INTO analytics.fact_sales
    SELECT si.sale_id,
           si.line_no,
           to_char(pharma.business_date(si.sold_at), 'YYYYMMDD')::integer,
           s.branch_id,
           b.drug_id,
           coalesce(s.customer_id, 0),
           si.quantity,
           si.quantity * si.unit_price,
           CASE WHEN s.gross_amount > 0
                THEN round(s.discount_amount * (si.quantity * si.unit_price) / s.gross_amount, 2)
                ELSE 0 END,
           si.quantity * si.unit_price
             - CASE WHEN s.gross_amount > 0
                    THEN round(s.discount_amount * (si.quantity * si.unit_price) / s.gross_amount, 2)
                    ELSE 0 END
      FROM pharma.sale_item si
      JOIN pharma.sale s  ON s.sale_id = si.sale_id AND s.sold_at = si.sold_at
      JOIN pharma.batch b ON b.batch_id = si.batch_id
     WHERE si.sold_at > v_from AND si.sold_at <= v_to
    ON CONFLICT (sale_id, line_no) DO NOTHING;

    UPDATE analytics.etl_state
       SET last_sale_ts = greatest(last_sale_ts, v_to),
           refreshed_at = now();
END
$$;

-- Branch scoping applies to analytics too, otherwise the star schema would
-- be a side door around RLS.
ALTER TABLE analytics.fact_sales ENABLE ROW LEVEL SECURITY;
CREATE POLICY reader_scope ON analytics.fact_sales FOR SELECT TO sorvia_reader
    USING ((SELECT sorvia.scope_all_branches()) OR branch_key = (SELECT sorvia.scope_branch_id()));
CREATE POLICY app_all ON analytics.fact_sales TO sorvia_app USING (true) WITH CHECK (true);

GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO sorvia_reader, sorvia_app;
REVOKE SELECT ON analytics.etl_state FROM sorvia_reader;
REVOKE EXECUTE ON PROCEDURE analytics.refresh(boolean) FROM PUBLIC;
GRANT EXECUTE ON PROCEDURE analytics.refresh(boolean) TO sorvia_app;

COMMENT ON TABLE analytics.fact_sales IS
'Analitik satış faktları (ulduz sxemi): hər satış sətri üçün miqdar, ümumi məbləğ, endirim, xalis məbləğ. dim_date, dim_branch, dim_drug, dim_customer ilə birləşdirilir. Böyük həcmli analitik hesabatlar üçün sürətlidir.';
COMMENT ON TABLE analytics.dim_date IS 'Tarix ölçüsü: il, rüb, ay, ayın adı, həftənin günü, həftəsonu.';
COMMENT ON TABLE analytics.dim_branch IS 'Filial ölçüsü: kod, ad, şəhər.';
COMMENT ON TABLE analytics.dim_drug IS 'Dərman ölçüsü: ad, təsiredici maddə, kateqoriya, istehsalçı, ölkə, forma, reseptli.';
COMMENT ON TABLE analytics.dim_customer IS 'Müştəri ölçüsü: yaş qrupu, cins, şəhər. 0 = anonim müştəri.';
