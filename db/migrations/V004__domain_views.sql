-- V004: reporting views.
--
-- Every view is created WITH (security_invoker = true). Without it a view runs
-- with the privileges of its owner and silently bypasses Row-Level Security of
-- the underlying tables. With it, a branch pharmacist querying a view sees
-- exactly the rows RLS allows on the base tables.

SET search_path = pharma, public;

CREATE VIEW pharma.v_drug_catalog WITH (security_invoker = true) AS
SELECT d.drug_id,
       d.trade_name,
       d.active_ingredient,
       d.dosage_form,
       d.strength,
       d.requires_prescription,
       d.unit_price,
       c.name  AS category_name,
       m.name  AS manufacturer_name,
       m.country AS manufacturer_country
  FROM pharma.drug d
  JOIN pharma.category c     USING (category_id)
  JOIN pharma.manufacturer m USING (manufacturer_id);

CREATE VIEW pharma.v_sale_lines WITH (security_invoker = true) AS
SELECT si.sale_id,
       si.sold_at,
       pharma.business_date(si.sold_at) AS sale_date,
       s.branch_id,
       br.name     AS branch_name,
       br.city     AS branch_city,
       s.employee_id,
       s.customer_id,
       si.line_no,
       b.drug_id,
       d.trade_name,
       d.active_ingredient,
       c.name      AS category_name,
       si.batch_id,
       si.quantity,
       si.unit_price,
       si.quantity * si.unit_price AS line_amount
  FROM pharma.sale_item si
  JOIN pharma.sale s      ON s.sale_id = si.sale_id AND s.sold_at = si.sold_at
  JOIN pharma.branch br   ON br.branch_id = s.branch_id
  JOIN pharma.batch b     ON b.batch_id = si.batch_id
  JOIN pharma.drug d      ON d.drug_id = b.drug_id
  JOIN pharma.category c  ON c.category_id = d.category_id;

CREATE VIEW pharma.v_stock_by_drug WITH (security_invoker = true) AS
SELECT st.branch_id,
       br.name AS branch_name,
       b.drug_id,
       d.trade_name,
       d.min_stock,
       sum(st.quantity) AS quantity
  FROM pharma.stock st
  JOIN pharma.branch br ON br.branch_id = st.branch_id
  JOIN pharma.batch b   ON b.batch_id = st.batch_id
  JOIN pharma.drug d    ON d.drug_id = b.drug_id
 WHERE b.expires_on >= current_date
 GROUP BY st.branch_id, br.name, b.drug_id, d.trade_name, d.min_stock;

CREATE VIEW pharma.v_low_stock WITH (security_invoker = true) AS
SELECT *
  FROM pharma.v_stock_by_drug
 WHERE quantity < min_stock;

CREATE VIEW pharma.v_expiring_soon WITH (security_invoker = true) AS
SELECT st.branch_id,
       br.name AS branch_name,
       b.batch_id,
       b.lot_number,
       d.trade_name,
       b.expires_on,
       b.expires_on - current_date AS days_left,
       st.quantity
  FROM pharma.stock st
  JOIN pharma.branch br ON br.branch_id = st.branch_id
  JOIN pharma.batch b   ON b.batch_id = st.batch_id
  JOIN pharma.drug d    ON d.drug_id = b.drug_id
 WHERE st.quantity > 0
   AND b.expires_on BETWEEN current_date AND current_date + 30;

CREATE VIEW pharma.v_branch_monthly_revenue WITH (security_invoker = true) AS
SELECT s.branch_id,
       br.name AS branch_name,
       date_trunc('month', s.sold_at AT TIME ZONE 'Asia/Baku')::date AS month,
       count(*)              AS sale_count,
       sum(s.gross_amount)   AS gross_revenue,
       sum(s.discount_amount) AS discounts,
       sum(s.net_amount)     AS net_revenue
  FROM pharma.sale s
  JOIN pharma.branch br ON br.branch_id = s.branch_id
 GROUP BY s.branch_id, br.name, date_trunc('month', s.sold_at AT TIME ZONE 'Asia/Baku')::date;
