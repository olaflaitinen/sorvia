"""Builds benchmark/data/az_text2sql_v1.jsonl.

Each record: id, difficulty (easy | medium | hard), question (Azerbaijani),
question_en (English parallel), sql (gold), ordered (row order matters), tags.
Relative dates are expressed with current_date so that the gold answer is
always computed on the same snapshot as the prediction.
"""

import json
from pathlib import Path

D = []


def q(id_, diff, az, en, sql, ordered=False, tags=()):
    D.append({"id": f"q{id_:03d}", "difficulty": diff, "question": az, "question_en": en,
              "sql": " ".join(sql.split()), "ordered": ordered, "tags": list(tags)})

# ---------------- easy ----------------
q(1, "easy", "Şəbəkədə neçə filial var?", "How many branches does the network have?",
  "SELECT count(*) AS branch_count FROM pharma.branch")
q(2, "easy", "Bakıda neçə filial var?", "How many branches are in Baku?",
  "SELECT count(*) AS branch_count FROM pharma.branch WHERE city = 'Bakı'")
q(3, "easy", "Ən bahalı 5 dərman hansılardır?", "Which are the 5 most expensive drugs?",
  "SELECT trade_name, strength, dosage_form, unit_price FROM pharma.drug ORDER BY unit_price DESC LIMIT 5", True, ["ranking"])
q(4, "easy", "Reseptlə satılan neçə dərman var?", "How many drugs are prescription-only?",
  "SELECT count(*) AS rx_drugs FROM pharma.drug WHERE requires_prescription")
q(5, "easy", "Hansı istehsalçılar Türkiyədəndir?", "Which manufacturers are from Turkey?",
  "SELECT name FROM pharma.manufacturer WHERE country = 'Türkiyə'")
q(6, "easy", "Hazırda neçə aktiv işçi var?", "How many active employees are there?",
  "SELECT count(*) AS active_employees FROM pharma.employee WHERE is_active")
q(7, "easy", "Dərmanların orta qiyməti nə qədərdir?", "What is the average drug price?",
  "SELECT round(avg(unit_price), 2) AS avg_price FROM pharma.drug")
q(8, "easy", "Sirop formasında olan dərmanları göstər", "Show the drugs that come as a syrup",
  "SELECT trade_name, strength FROM pharma.drug WHERE dosage_form = 'syrup'")
q(9, "easy", "Bonus balı 100-dən çox olan neçə müştəri var?", "How many customers have more than 100 bonus points?",
  "SELECT count(*) AS customers FROM pharma.customer WHERE bonus_points > 100")
q(10, "easy", "Bazada neçə həkim var?", "How many doctors are in the database?",
  "SELECT count(*) AS doctors FROM pharma.doctor")
q(11, "easy", "Kardioloq həkimlərin siyahısı", "List the cardiologists",
  "SELECT first_name, last_name, clinic FROM pharma.doctor WHERE specialty = 'Kardioloq'")
q(12, "easy", "Vaxtı keçmiş neçə partiya var?", "How many batches have expired?",
  "SELECT count(*) AS expired_batches FROM pharma.batch WHERE expires_on < current_date")
q(13, "easy", "Gəncədəki filialların adları və ünvanları", "Names and addresses of the branches in Ganja",
  "SELECT name, address FROM pharma.branch WHERE city = 'Gəncə'")
q(14, "easy", "Paracetamol tərkibli dərmanlar hansılardır?", "Which drugs contain paracetamol?",
  "SELECT trade_name, strength, dosage_form FROM pharma.drug WHERE active_ingredient ILIKE '%paracetamol%'")
q(15, "easy", "İndiyə qədər neçə satış olub?", "How many sales have been made so far?",
  "SELECT count(*) AS sales FROM pharma.sale")

# ---------------- medium ----------------
q(16, "medium", "Hər kateqoriyada neçə dərman var?", "How many drugs are in each category?",
  "SELECT c.name AS category, count(*) AS drug_count FROM pharma.drug d JOIN pharma.category c ON c.category_id = d.category_id GROUP BY c.name",
  tags=["join", "group"])
q(17, "medium", "Hər filialda neçə aktiv işçi işləyir?", "How many active employees work in each branch?",
  "SELECT b.name AS branch, count(*) AS employees FROM pharma.employee e JOIN pharma.branch b ON b.branch_id = e.branch_id WHERE e.is_active GROUP BY b.name",
  tags=["join", "group"])
q(18, "medium", "Hər ölkədən neçə istehsalçı var?", "How many manufacturers are there per country?",
  "SELECT country, count(*) AS manufacturers FROM pharma.manufacturer GROUP BY country", tags=["group"])
q(19, "medium", "Hansı istehsalçı ən çox dərman çeşidi təqdim edir?", "Which manufacturer supplies the most drug products?",
  "SELECT m.name, count(*) AS drug_count FROM pharma.drug d JOIN pharma.manufacturer m ON m.manufacturer_id = d.manufacturer_id GROUP BY m.name ORDER BY drug_count DESC, m.name LIMIT 1",
  True, ["join", "ranking"])
q(20, "medium", "Hər şəhər üzrə ümumi xalis gəlir nə qədərdir?", "What is the total net revenue per city?",
  "SELECT b.city, sum(s.net_amount) AS net_revenue FROM pharma.sale s JOIN pharma.branch b ON b.branch_id = s.branch_id GROUP BY b.city",
  tags=["join", "group"])
q(21, "medium", "Keçən ay neçə satış olub?", "How many sales were made last month?",
  "SELECT count(*) AS sales FROM pharma.sale WHERE pharma.business_date(sold_at) >= (date_trunc('month', current_date) - interval '1 month')::date AND pharma.business_date(sold_at) < date_trunc('month', current_date)::date",
  tags=["date"])
q(22, "medium", "Bu il miqdarca ən çox satılan 10 dərman", "Top 10 drugs by quantity sold this year",
  "SELECT trade_name, sum(quantity) AS units FROM pharma.v_sale_lines WHERE sale_date >= date_trunc('year', current_date)::date GROUP BY trade_name ORDER BY units DESC LIMIT 10",
  True, ["date", "ranking"])
q(23, "medium", "Son 6 ayda aylar üzrə xalis gəlir", "Net revenue by month over the last 6 months",
  "SELECT date_trunc('month', pharma.business_date(sold_at))::date AS month, sum(net_amount) AS net_revenue FROM pharma.sale WHERE pharma.business_date(sold_at) >= (date_trunc('month', current_date) - interval '5 months')::date GROUP BY 1 ORDER BY 1",
  True, ["date", "group"])
q(24, "medium", "Filiallar üzrə orta çek məbləği", "Average receipt amount per branch",
  "SELECT b.name AS branch, round(avg(s.net_amount), 2) AS avg_receipt FROM pharma.sale s JOIN pharma.branch b ON b.branch_id = s.branch_id GROUP BY b.name",
  tags=["join", "group"])
q(25, "medium", "Hansı müştəri ən çox pul xərcləyib?", "Which customer has spent the most money?",
  "SELECT c.first_name, c.last_name, sum(s.net_amount) AS total_spent FROM pharma.sale s JOIN pharma.customer c ON c.customer_id = s.customer_id GROUP BY c.customer_id, c.first_name, c.last_name ORDER BY total_spent DESC LIMIT 1",
  True, ["join", "ranking"])
q(26, "medium", "Satışların neçə faizi reseptlə olub?", "What percentage of sales were made with a prescription?",
  "SELECT round(100.0 * count(*) FILTER (WHERE prescription_id IS NOT NULL) / count(*), 2) AS rx_share_pct FROM pharma.sale",
  tags=["ratio"])
q(27, "medium", "Ən çox resept yazan 10 həkim", "The 10 doctors who wrote the most prescriptions",
  "SELECT d.first_name, d.last_name, count(*) AS prescriptions FROM pharma.prescription p JOIN pharma.doctor d ON d.doctor_id = p.doctor_id GROUP BY d.doctor_id, d.first_name, d.last_name ORDER BY prescriptions DESC, d.doctor_id LIMIT 10",
  True, ["join", "ranking"])
q(28, "medium", "Yaxın 30 gündə vaxtı bitəcək partiyalar hansı filiallardadır?", "Which branches hold batches that expire within 30 days?",
  "SELECT DISTINCT branch_name FROM pharma.v_expiring_soon", tags=["view"])
q(29, "medium", "BAK01 filialında qalığı minimumdan az olan dərmanlar", "Drugs below minimum stock in branch BAK01",
  "SELECT l.trade_name, l.quantity, l.min_stock FROM pharma.v_low_stock l JOIN pharma.branch b ON b.branch_id = l.branch_id WHERE b.code = 'BAK01'",
  tags=["view", "join"])
q(30, "medium", "Həftəsonu və iş günlərində satış sayını müqayisə et", "Compare the number of sale lines on weekends and weekdays",
  "SELECT d.is_weekend, count(*) AS sale_lines FROM analytics.fact_sales f JOIN analytics.dim_date d ON d.date_key = f.date_key GROUP BY d.is_weekend",
  tags=["olap"])
q(31, "medium", "Bu il rüblər üzrə xalis gəlir", "Net revenue by quarter this year",
  "SELECT d.quarter, sum(f.net_amount) AS net_revenue FROM analytics.fact_sales f JOIN analytics.dim_date d ON d.date_key = f.date_key WHERE d.year = extract(year FROM current_date) GROUP BY d.quarter ORDER BY d.quarter",
  True, ["olap", "date"])
q(32, "medium", "Müştərilərin yaş qrupları üzrə satış məbləği", "Sales amount by customer age group",
  "SELECT c.age_group, sum(f.net_amount) AS net_revenue FROM analytics.fact_sales f JOIN analytics.dim_customer c ON c.customer_key = f.customer_key GROUP BY c.age_group",
  tags=["olap"])
q(33, "medium", "Hansı dərman forması miqdarca ən çox satılır?", "Which dosage form sells the most units?",
  "SELECT d.dosage_form, sum(si.quantity) AS units FROM pharma.sale_item si JOIN pharma.batch b ON b.batch_id = si.batch_id JOIN pharma.drug d ON d.drug_id = b.drug_id GROUP BY d.dosage_form ORDER BY units DESC LIMIT 1",
  True, ["join", "ranking"])
q(34, "medium", "Bu il ümumi endirim məbləği nə qədər olub?", "What is the total discount given this year?",
  "SELECT sum(discount_amount) AS total_discount FROM pharma.sale WHERE pharma.business_date(sold_at) >= date_trunc('year', current_date)::date",
  tags=["date"])
q(35, "medium", "Satış sayına görə ən yaxşı 5 işçi", "Top 5 employees by number of sales",
  "SELECT e.first_name, e.last_name, count(*) AS sales FROM pharma.sale s JOIN pharma.employee e ON e.employee_id = s.employee_id GROUP BY e.employee_id, e.first_name, e.last_name ORDER BY sales DESC, e.employee_id LIMIT 5",
  True, ["join", "ranking"])
q(36, "medium", "Son 7 gündə gündəlik satış sayı", "Daily number of sales over the last 7 days",
  "SELECT pharma.business_date(sold_at) AS day, count(*) AS sales FROM pharma.sale WHERE pharma.business_date(sold_at) >= current_date - 7 GROUP BY 1 ORDER BY 1",
  True, ["date"])
q(37, "medium", "Bu il ən az gəlir gətirən filial hansıdır?", "Which branch brought in the least revenue this year?",
  "SELECT b.name, sum(s.net_amount) AS net_revenue FROM pharma.sale s JOIN pharma.branch b ON b.branch_id = s.branch_id WHERE pharma.business_date(s.sold_at) >= date_trunc('year', current_date)::date GROUP BY b.name ORDER BY net_revenue ASC LIMIT 1",
  True, ["date", "ranking"])
q(38, "medium", "Kateqoriyalar üzrə orta dərman qiyməti", "Average drug price per category",
  "SELECT c.name AS category, round(avg(d.unit_price), 2) AS avg_price FROM pharma.drug d JOIN pharma.category c ON c.category_id = d.category_id GROUP BY c.name",
  tags=["join", "group"])
q(39, "medium", "Hansı həkim ixtisası ən çox resept yazıb?", "Which medical specialty wrote the most prescriptions?",
  "SELECT d.specialty, count(*) AS prescriptions FROM pharma.prescription p JOIN pharma.doctor d ON d.doctor_id = p.doctor_id GROUP BY d.specialty ORDER BY prescriptions DESC LIMIT 1",
  True, ["join", "ranking"])
q(40, "medium", "Vəzifələr üzrə orta maaş", "Average salary by job position",
  "SELECT jp.name AS position, round(avg(e.salary), 2) AS avg_salary FROM pharma.employee e JOIN pharma.job_position jp ON jp.position_id = e.position_id GROUP BY jp.name",
  tags=["join", "group"])
q(41, "medium", "Qadın və kişi müştərilərin orta çek məbləği", "Average receipt amount of female and male customers",
  "SELECT c.gender, round(avg(s.net_amount), 2) AS avg_receipt FROM pharma.sale s JOIN pharma.customer c ON c.customer_id = s.customer_id GROUP BY c.gender",
  tags=["join", "group"])
q(42, "medium", "Hansı filialda ən çox reseptli satış olub?", "Which branch made the most prescription sales?",
  "SELECT b.name, count(*) AS rx_sales FROM pharma.sale s JOIN pharma.branch b ON b.branch_id = s.branch_id WHERE s.prescription_id IS NOT NULL GROUP BY b.name ORDER BY rx_sales DESC LIMIT 1",
  True, ["join", "ranking"])
q(43, "medium", "İstehsalçı ölkələri üzrə bu ilki satış məbləği", "Sales amount by manufacturer country this year",
  "SELECT dd.manufacturer_country, sum(f.net_amount) AS net_revenue FROM analytics.fact_sales f JOIN analytics.dim_drug dd ON dd.drug_key = f.drug_key JOIN analytics.dim_date d ON d.date_key = f.date_key WHERE d.year = extract(year FROM current_date) GROUP BY dd.manufacturer_country",
  tags=["olap", "date"])
q(44, "medium", "Filiallar arası neçə köçürmə edilib?", "How many transfers between branches have been made?",
  "SELECT count(*) AS transfers FROM pharma.stock_transfer")
q(45, "medium", "Bir çekdə orta hesabla neçə sətir olur?", "How many lines does a receipt have on average?",
  "SELECT round(avg(n), 2) AS avg_lines FROM (SELECT count(*) AS n FROM pharma.sale_item GROUP BY sale_id, sold_at) t",
  tags=["subquery"])

# ---------------- hard ----------------
q(46, "hard", "Antibiotiklər qrupunun (alt kateqoriyalar daxil) bu ilki satış məbləği", "This year's sales amount of the antibiotics group, subcategories included",
  "SELECT sum(si.quantity * si.unit_price) AS revenue FROM pharma.sale_item si JOIN pharma.batch b ON b.batch_id = si.batch_id JOIN pharma.drug d ON d.drug_id = b.drug_id JOIN pharma.category c ON c.category_id = d.category_id LEFT JOIN pharma.category p ON p.category_id = c.parent_id WHERE (c.name = 'Antibiotiklər' OR p.name = 'Antibiotiklər') AND pharma.business_date(si.sold_at) >= date_trunc('year', current_date)::date",
  tags=["hierarchy", "date"])
q(47, "hard", "Hər filialda ən çox satılan dərman hansıdır?", "What is the best-selling drug in each branch?",
  "SELECT branch_name, trade_name, units FROM (SELECT branch_name, trade_name, sum(quantity) AS units, rank() OVER (PARTITION BY branch_name ORDER BY sum(quantity) DESC) AS rnk FROM pharma.v_sale_lines GROUP BY branch_name, trade_name) t WHERE rnk = 1",
  tags=["window"])
q(48, "hard", "Son 12 ayda aylıq gəlirin əvvəlki aya görə faizlə dəyişməsi", "Month-over-month revenue change in percent over the last 12 months",
  "WITH m AS (SELECT date_trunc('month', pharma.business_date(sold_at))::date AS month, sum(net_amount) AS revenue FROM pharma.sale WHERE pharma.business_date(sold_at) >= (date_trunc('month', current_date) - interval '12 months')::date GROUP BY 1) SELECT month, revenue, round(100 * (revenue - lag(revenue) OVER (ORDER BY month)) / lag(revenue) OVER (ORDER BY month), 2) AS change_pct FROM m ORDER BY month",
  True, ["window", "date"])
q(49, "hard", "Son 7 gündə heç satılmamış dərmanlar", "Drugs that have not been sold at all in the last 7 days",
  "SELECT d.trade_name, d.strength, d.dosage_form FROM pharma.drug d WHERE NOT EXISTS (SELECT 1 FROM pharma.sale_item si JOIN pharma.batch b ON b.batch_id = si.batch_id WHERE b.drug_id = d.drug_id AND pharma.business_date(si.sold_at) >= current_date - 7)",
  tags=["anti-join"])
q(50, "hard", "Vaxtı keçmiş, amma anbarda qalan dərmanların filiallar üzrə ümumi dəyəri", "Total value of expired stock still on the shelves, per branch",
  "SELECT br.name AS branch, sum(st.quantity * d.unit_price) AS expired_value FROM pharma.stock st JOIN pharma.batch b ON b.batch_id = st.batch_id JOIN pharma.drug d ON d.drug_id = b.drug_id JOIN pharma.branch br ON br.branch_id = st.branch_id WHERE b.expires_on < current_date AND st.quantity > 0 GROUP BY br.name",
  tags=["join", "group"])
q(51, "hard", "Müştərilərin neçə faizi birdən çox alış edib?", "What percentage of customers made more than one purchase?",
  "SELECT round(100.0 * count(*) FILTER (WHERE n > 1) / count(*), 2) AS repeat_pct FROM (SELECT customer_id, count(*) AS n FROM pharma.sale WHERE customer_id IS NOT NULL GROUP BY customer_id) t",
  tags=["subquery", "ratio"])
q(52, "hard", "Hər şəhərdə ən çox gəlir gətirən filial", "The highest-revenue branch in each city",
  "SELECT city, name, revenue FROM (SELECT b.city, b.name, sum(s.net_amount) AS revenue, rank() OVER (PARTITION BY b.city ORDER BY sum(s.net_amount) DESC) AS rnk FROM pharma.sale s JOIN pharma.branch b ON b.branch_id = s.branch_id GROUP BY b.city, b.name) t WHERE rnk = 1",
  tags=["window"])
q(53, "hard", "Bu il Bakı filiallarının gəlirini Bakıdan kənar filiallarla müqayisə et", "Compare this year's revenue of Baku branches with branches outside Baku",
  "SELECT CASE WHEN b.city = 'Bakı' THEN 'Bakı' ELSE 'Regionlar' END AS region, sum(s.net_amount) AS net_revenue FROM pharma.sale s JOIN pharma.branch b ON b.branch_id = s.branch_id WHERE pharma.business_date(s.sold_at) >= date_trunc('year', current_date)::date GROUP BY 1",
  tags=["case", "date"])
q(54, "hard", "Bu ayın satış sayını keçən ilin eyni ayı ilə müqayisə et", "Compare this month's number of sales with the same month last year",
  "SELECT count(*) FILTER (WHERE pharma.business_date(sold_at) >= date_trunc('month', current_date)::date) AS this_month, count(*) FILTER (WHERE pharma.business_date(sold_at) >= (date_trunc('month', current_date) - interval '1 year')::date AND pharma.business_date(sold_at) < (date_trunc('month', current_date) - interval '11 months')::date) AS same_month_last_year FROM pharma.sale",
  tags=["date", "ratio"])
q(55, "hard", "Gəncə filiallarında bu il neçə ədəd antibiotik satılıb?", "How many antibiotic units were sold in Ganja branches this year?",
  "SELECT sum(si.quantity) AS units FROM pharma.sale_item si JOIN pharma.sale s ON s.sale_id = si.sale_id AND s.sold_at = si.sold_at JOIN pharma.branch br ON br.branch_id = s.branch_id JOIN pharma.batch b ON b.batch_id = si.batch_id JOIN pharma.drug d ON d.drug_id = b.drug_id JOIN pharma.category c ON c.category_id = d.category_id LEFT JOIN pharma.category p ON p.category_id = c.parent_id WHERE br.city = 'Gəncə' AND (c.name = 'Antibiotiklər' OR p.name = 'Antibiotiklər') AND pharma.business_date(si.sold_at) >= date_trunc('year', current_date)::date",
  tags=["hierarchy", "date", "join"])
q(56, "hard", "Bonus balı ən yüksək 10 müştəri və onların ümumi alış məbləği", "The 10 customers with the most bonus points and their total spending",
  "SELECT c.first_name, c.last_name, c.bonus_points, coalesce(sum(s.net_amount), 0) AS total_spent FROM pharma.customer c LEFT JOIN pharma.sale s ON s.customer_id = c.customer_id GROUP BY c.customer_id, c.first_name, c.last_name, c.bonus_points ORDER BY c.bonus_points DESC, c.customer_id LIMIT 10",
  True, ["join", "ranking"])
q(57, "hard", "Hər filial üzrə satılan məhsulların neçə faizi reseptli dərmanlardır?", "Per branch, what share of units sold are prescription drugs?",
  "SELECT branch_name, round(100.0 * sum(quantity) FILTER (WHERE d.requires_prescription) / sum(quantity), 2) AS rx_units_pct FROM pharma.v_sale_lines v JOIN pharma.drug d ON d.drug_id = v.drug_id GROUP BY branch_name",
  tags=["ratio", "view"])
q(58, "hard", "Son 3 ayın hər birində ən çox gəlir gətirən gün", "The highest-revenue day in each of the last 3 months",
  "SELECT month, day, revenue FROM (SELECT date_trunc('month', pharma.business_date(sold_at))::date AS month, pharma.business_date(sold_at) AS day, sum(net_amount) AS revenue, rank() OVER (PARTITION BY date_trunc('month', pharma.business_date(sold_at)) ORDER BY sum(net_amount) DESC) AS rnk FROM pharma.sale WHERE pharma.business_date(sold_at) >= (date_trunc('month', current_date) - interval '2 months')::date GROUP BY 1, 2) t WHERE rnk = 1",
  tags=["window", "date"])
q(59, "hard", "Ən çox köçürmə alan filial hansıdır?", "Which branch received the most transfers?",
  "SELECT b.name, count(*) AS transfers_in FROM pharma.stock_transfer t JOIN pharma.branch b ON b.branch_id = t.to_branch_id GROUP BY b.name ORDER BY transfers_in DESC LIMIT 1",
  True, ["join", "ranking"])
q(60, "hard", "Qış aylarında (dekabr-fevral) soyuqdəymə dərmanlarının satış miqdarı yay aylarından neçə dəfə çoxdur?", "How many times more cold-and-cough units are sold in winter (Dec-Feb) than in summer (Jun-Aug)?",
  "SELECT round(sum(f.quantity) FILTER (WHERE d.month IN (12, 1, 2))::numeric / nullif(sum(f.quantity) FILTER (WHERE d.month IN (6, 7, 8)), 0), 2) AS winter_to_summer_ratio FROM analytics.fact_sales f JOIN analytics.dim_date d ON d.date_key = f.date_key JOIN analytics.dim_drug dd ON dd.drug_key = f.drug_key WHERE dd.category_name = 'Soyuqdəymə və öskürək'",
  tags=["olap", "ratio"])

OUT = Path(__file__).parent / "data" / "az_text2sql_v1.jsonl"
with OUT.open("w", encoding="utf-8") as fh:
    for r in D:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"Wrote {len(D)} questions to {OUT}")
