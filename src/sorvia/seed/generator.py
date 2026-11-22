"""Deterministic synthetic data generator.

Generates a consistent history for the ŞəfaNet pharmacy network: master data,
batches, receipts, prescriptions, sales and the movement ledger. Stock is
simulated in memory with the same rules the database enforces (FEFO
allocation, no expired sales, prescriptions for Rx drugs, no negative stock),
so the loaded data satisfies every trigger even though triggers are disabled
during the bulk load for speed (session_replication_role = replica).

The same --seed and --today always produce the same database.
"""

from __future__ import annotations

import bisect
import datetime as dt
import logging
import math
import random
import string
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql

from sorvia.seed import catalog

log = logging.getLogger(__name__)

BAKU = ZoneInfo("Asia/Baku")

DOMAIN_TABLES = (
    "pharma.batch_movement", "pharma.stock_transfer", "pharma.sale_item", "pharma.sale",
    "pharma.prescription_item", "pharma.prescription", "pharma.doctor", "pharma.customer",
    "pharma.stock", "pharma.batch", "pharma.drug", "pharma.category", "pharma.manufacturer",
    "pharma.employee", "pharma.job_position", "pharma.branch",
)


@dataclass
class SeedConfig:
    scale: float = 1.0
    seed: int = 42
    today: dt.date = field(default_factory=dt.date.today)
    days: int = 540

    @property
    def sales(self) -> int:
        return max(1000, int(50_000 * self.scale))

    @property
    def customers(self) -> int:
        return max(500, min(150_000, int(8_000 * math.sqrt(max(self.scale, 0.01)) * 2)))

    @property
    def doctors(self) -> int:
        return 240


class WeightedChoice:
    """O(log n) weighted sampling with a precomputed cumulative table."""

    def __init__(self, items: list[Any], weights: list[float]) -> None:
        self.items = items
        self.cum: list[float] = []
        total = 0.0
        for w in weights:
            total += w
            self.cum.append(total)
        self.total = total

    def pick(self, rng: random.Random) -> Any:
        return self.items[bisect.bisect_right(self.cum, rng.random() * self.total)]


@dataclass
class _Drug:
    drug_id: int
    ingredient: catalog.Ingredient
    price: float
    rx: bool
    batches: list[tuple[int, dt.date, dt.date]] = field(default_factory=list)  # (batch_id, made, expires)


class Generator:
    def __init__(self, cfg: SeedConfig) -> None:
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.rows: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
        self.fins: list[tuple[int, str]] = []
        self.start = cfg.today - dt.timedelta(days=cfg.days)

    # -- master data -------------------------------------------------------------

    def _person(self) -> tuple[str, str, str]:
        if self.rng.random() < 0.5:
            return self.rng.choice(catalog.MALE_FIRST), self.rng.choice(catalog.LAST_STEMS), "M"
        return self.rng.choice(catalog.FEMALE_FIRST), self.rng.choice(catalog.LAST_STEMS) + "a", "F"

    def _phone(self) -> str:
        return "+994" + self.rng.choice(("50", "51", "55", "70", "77", "99")) + "".join(
            self.rng.choice(string.digits) for _ in range(7))

    def master_data(self) -> None:
        rng = self.rng
        for i, (code, name, city, address, _w) in enumerate(catalog.BRANCHES, start=1):
            opened = dt.date(2015, 1, 1) + dt.timedelta(days=rng.randint(0, 2900))
            self.rows["branch"].append((i, code, name, city, address, self._phone(), opened))
        for i, name in enumerate(catalog.POSITIONS, start=1):
            self.rows["job_position"].append((i, name))

        self.branch_staff: dict[int, list[int]] = defaultdict(list)
        emp_id = 0
        for branch_id in range(1, len(catalog.BRANCHES) + 1):
            weight = catalog.BRANCHES[branch_id - 1][4]
            staff = [(3, 1)] + [(1, 1)] * max(2, round(2 * weight)) + [(2, 1)] * max(1, round(weight)) + [(4, 1)]
            for position_id, _ in staff:
                emp_id += 1
                first, last, _g = self._person()
                salary = {1: 1100, 2: 750, 3: 1600, 4: 800}[position_id] + rng.randint(0, 300)
                hired = self.start - dt.timedelta(days=rng.randint(30, 2500))
                active = rng.random() > 0.05
                self.rows["employee"].append((emp_id, branch_id, position_id, first, last, hired, salary, active))
                if position_id in (1, 2) and active:
                    self.branch_staff[branch_id].append(emp_id)

        for i, (name, country) in enumerate(catalog.MANUFACTURERS, start=1):
            self.rows["manufacturer"].append((i, name, country))

        cat_ids: dict[str, int] = {}
        for i, (name, parent) in enumerate(catalog.CATEGORIES, start=1):
            cat_ids[name] = i
            self.rows["category"].append((i, name, cat_ids[parent] if parent else None))

        self.drugs: list[_Drug] = []
        drug_id = 0
        for ing in catalog.INGREDIENTS:
            for brand in ing.brands:
                manufacturer_id = rng.randint(1, len(catalog.MANUFACTURERS))
                brand_factor = rng.uniform(0.85, 1.35)
                for form, strength in ing.variants:
                    drug_id += 1
                    price = round(ing.base_price * catalog.FORM_PRICE_FACTOR[form] * brand_factor, 2)
                    min_stock = 10 if ing.popularity < 1 else 20
                    self.rows["drug"].append((drug_id, brand, ing.name, cat_ids[ing.category], manufacturer_id,
                                              form, strength, ing.rx, price, min_stock))
                    self.drugs.append(_Drug(drug_id, ing, price, ing.rx))

        batch_id = 0
        for d in self.drugs:
            made = self.start - dt.timedelta(days=rng.randint(200, 420))
            while made < self.cfg.today:
                batch_id += 1
                shelf = rng.choice((540, 730, 1095))
                expires = made + dt.timedelta(days=shelf)
                lot = f"{d.ingredient.name[:3].upper()}{made:%y%m}-{batch_id:05d}"
                self.rows["batch"].append((batch_id, d.drug_id, lot, made, expires))
                d.batches.append((batch_id, made, expires))
                made += dt.timedelta(days=rng.randint(70, 130))

        for i in range(1, self.cfg.doctors + 1):
            first, last, _g = self._person()
            self.rows["doctor"].append((i, first, last, rng.choice(catalog.CLINICS),
                                        rng.choice(catalog.SPECIALTIES), f"AZ-MD-{100000 + i}"))

        cities = [b[2] for b in catalog.BRANCHES]
        city_weights = [b[4] for b in catalog.BRANCHES]
        city_pick = WeightedChoice(cities, city_weights)
        for i in range(1, self.cfg.customers + 1):
            first, last, gender = self._person()
            birth_year = rng.randint(1945, 2006)
            created = dt.datetime.combine(self.start - dt.timedelta(days=rng.randint(0, 900)),
                                          dt.time(rng.randint(9, 20), rng.randint(0, 59)), BAKU)
            fin = "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(7))
            self.fins.append((i, fin))
            self.rows["customer"].append((i, first, last, self._phone(), birth_year, gender,
                                          city_pick.pick(rng), 0, created))

    # -- transactional history -------------------------------------------------

    def _day_weights(self) -> list[tuple[dt.date, float]]:
        out = []
        for i in range(self.cfg.days):
            day = self.start + dt.timedelta(days=i)
            w = 1.0 + 0.25 * i / self.cfg.days          # slow growth
            w *= {5: 1.1, 6: 0.8}.get(day.weekday(), 1.0)
            if day.month in (12, 1, 2):
                w *= 1.2
            out.append((day, w))
        return out

    def _drug_weights(self, month: int) -> list[float]:
        weights = []
        for d in self.drugs:
            w = d.ingredient.popularity * (0.45 if d.rx else 1.0)
            if d.ingredient.season == "winter" and month in (11, 12, 1, 2, 3):
                w *= 2.0
            if d.ingredient.season == "spring" and month in (4, 5, 6):
                w *= 2.5
            weights.append(w)
        return weights

    def history(self) -> None:
        rng = self.rng
        cfg = self.cfg
        branch_pick = WeightedChoice(list(range(1, len(catalog.BRANCHES) + 1)), [b[4] for b in catalog.BRANCHES])
        hours = list(range(8, 23))
        hour_pick = WeightedChoice(hours, [0.4, 0.7, 0.9, 1.0, 1.0, 1.1, 1.0, 1.0, 1.1, 1.3, 1.5, 1.6, 1.3, 0.9, 0.5])
        n_lines_pick = WeightedChoice([1, 2, 3, 4], [0.55, 0.28, 0.12, 0.05])
        qty_pick = WeightedChoice([1, 2, 3], [0.7, 0.22, 0.08])
        # A minority of loyal customers make most identified purchases.
        cust_ids = list(range(1, cfg.customers + 1))
        cust_pick = WeightedChoice(cust_ids, [1.0 / (i ** 0.6) for i in cust_ids])
        month_pickers = {m: WeightedChoice(self.drugs, self._drug_weights(m)) for m in range(1, 13)}

        days = self._day_weights()
        total_w = sum(w for _, w in days)
        stock: dict[tuple[int, int], int] = defaultdict(int)          # (branch, batch) -> qty
        bonus = [0] * (cfg.customers + 1)

        sale_id = line_total = rx_id = transfer_id = 0
        movement_id = 0
        target = cfg.sales
        carry = 0.0
        started = time.perf_counter()

        def receive(branch_id: int, d: _Drug, when: dt.datetime) -> bool:
            nonlocal movement_id
            day = when.date()
            usable = [b for b in d.batches
                      if b[1] + dt.timedelta(days=10) <= day and b[2] > day + dt.timedelta(days=60)]
            if not usable:
                return False
            batch_id = max(usable, key=lambda b: b[1])[0]
            weight = catalog.BRANCHES[branch_id - 1][4]
            qty = int(rng.randint(20, 60) * (0.6 + weight / 2) * (0.5 + d.ingredient.popularity / 2))
            stock[(branch_id, batch_id)] += qty
            movement_id += 1
            self.rows["batch_movement"].append(
                (movement_id, batch_id, branch_id, qty, "receipt", None, when - dt.timedelta(hours=rng.randint(1, 5))))
            return True

        for day, w in days:
            exact = target * w / total_w + carry
            n_today = int(exact)
            carry = exact - n_today
            times = sorted(
                dt.datetime.combine(day, dt.time(hour_pick.pick(rng), rng.randint(0, 59), rng.randint(0, 59)), BAKU)
                for _ in range(n_today)
            )
            picker = month_pickers[day.month]

            # Occasional rebalancing transfer from a large Baku branch to a smaller one.
            if rng.random() < 0.6:
                from_branch = rng.randint(1, 4)
                to_branch = rng.randint(5, len(catalog.BRANCHES))
                d = picker.pick(rng)
                movable = [b[0] for b in d.batches
                           if b[2] > day + dt.timedelta(days=60) and stock[(from_branch, b[0])] >= 20]
                if movable:
                    bid = movable[0]
                    qty = rng.randint(5, 15)
                    when = dt.datetime.combine(day, dt.time(7, 30), BAKU)
                    transfer_id += 1
                    stock[(from_branch, bid)] -= qty
                    stock[(to_branch, bid)] += qty
                    self.rows["stock_transfer"].append(
                        (transfer_id, from_branch, to_branch, bid, qty,
                         rng.choice(self.branch_staff[from_branch]), when))
                    movement_id += 1
                    self.rows["batch_movement"].append(
                        (movement_id, bid, from_branch, -qty, "transfer_out", transfer_id, when))
                    movement_id += 1
                    self.rows["batch_movement"].append(
                        (movement_id, bid, to_branch, qty, "transfer_in", transfer_id, when))

            for sold_at in times:
                branch_id = branch_pick.pick(rng)
                staff = self.branch_staff[branch_id]
                employee_id = rng.choice(staff)
                n_lines = n_lines_pick.pick(rng)
                chosen: dict[int, _Drug] = {}
                for _ in range(n_lines * 2):
                    d = picker.pick(rng)
                    chosen.setdefault(d.drug_id, d)
                    if len(chosen) == n_lines:
                        break
                has_rx = any(d.rx for d in chosen.values())
                customer_id = cust_pick.pick(rng) if (has_rx or rng.random() < 0.5) else None

                lines: list[tuple[int, int, float, _Drug]] = []   # (batch_id, qty, price, drug)
                for d in chosen.values():
                    want = qty_pick.pick(rng)
                    # FEFO: non-expired batches in this branch, earliest expiry first.
                    avail = sorted((b[2], b[0]) for b in d.batches
                                   if b[2] >= day and stock[(branch_id, b[0])] > 0)
                    if sum(stock[(branch_id, bid)] for _, bid in avail) < want:
                        if not receive(branch_id, d, sold_at):
                            continue
                        avail = sorted((b[2], b[0]) for b in d.batches
                                       if b[2] >= day and stock[(branch_id, b[0])] > 0)
                        if sum(stock[(branch_id, bid)] for _, bid in avail) < want:
                            continue
                    remaining = want
                    for _exp, bid in avail:
                        take = min(remaining, stock[(branch_id, bid)])
                        lines.append((bid, take, d.price, d))
                        stock[(branch_id, bid)] -= take
                        remaining -= take
                        if not remaining:
                            break
                if not lines:
                    continue

                prescription_id = None
                rx_lines = [ln for ln in lines if ln[3].rx]
                if rx_lines:
                    rx_id += 1
                    prescription_id = rx_id
                    issued = day - dt.timedelta(days=rng.randint(0, 5))
                    self.rows["prescription"].append(
                        (rx_id, customer_id, rng.randint(1, cfg.doctors), issued, issued + dt.timedelta(days=30)))
                    per_drug: dict[int, int] = defaultdict(int)
                    for _bid, q, _p, d in rx_lines:
                        per_drug[d.drug_id] += q
                    for drug_id, q in per_drug.items():
                        self.rows["prescription_item"].append((rx_id, drug_id, q, q))

                sale_id += 1
                gross = 0.0
                for line_no, (bid, q, price, _d) in enumerate(lines, start=1):
                    gross += q * price
                    line_total += 1
                    self.rows["sale_item"].append((sale_id, sold_at, line_no, bid, q, price))
                    movement_id += 1
                    self.rows["batch_movement"].append((movement_id, bid, branch_id, -q, "sale", sale_id, sold_at))
                gross = round(gross, 2)
                discount = 0.0
                if customer_id is not None:
                    pts = bonus[customer_id]
                    rate = 0.10 if pts >= 1000 else 0.05 if pts >= 500 else 0.02 if pts >= 100 else 0.0
                    discount = round(gross * rate, 2)
                    bonus[customer_id] += int((gross - discount) // 10)
                self.rows["sale"].append((sale_id, sold_at, branch_id, employee_id, customer_id,
                                          prescription_id, gross, discount))

        self.rows["stock"] = [(b, bt, q) for (b, bt), q in sorted(stock.items())]
        self.rows["customer"] = [(*r[:7], bonus[r[0]], *r[8:]) for r in self.rows["customer"]]
        log.info("Generated %s sales, %s lines, %s prescriptions in %.1fs",
                 sale_id, line_total, rx_id, time.perf_counter() - started)

    def generate(self) -> dict[str, list[tuple[Any, ...]]]:
        self.master_data()
        self.history()
        return self.rows


COLUMNS: dict[str, tuple[str, ...]] = {
    "branch": ("branch_id", "code", "name", "city", "address", "phone", "opened_on"),
    "job_position": ("position_id", "name"),
    "employee": ("employee_id", "branch_id", "position_id", "first_name", "last_name", "hired_on", "salary",
                 "is_active"),
    "manufacturer": ("manufacturer_id", "name", "country"),
    "category": ("category_id", "name", "parent_id"),
    "drug": ("drug_id", "trade_name", "active_ingredient", "category_id", "manufacturer_id", "dosage_form",
             "strength", "requires_prescription", "unit_price", "min_stock"),
    "batch": ("batch_id", "drug_id", "lot_number", "manufactured_on", "expires_on"),
    "doctor": ("doctor_id", "first_name", "last_name", "clinic", "specialty", "license_no"),
    "customer": ("customer_id", "first_name", "last_name", "phone", "birth_year", "gender", "city",
                 "bonus_points", "created_at"),
    "prescription": ("prescription_id", "customer_id", "doctor_id", "issued_on", "valid_until"),
    "prescription_item": ("prescription_id", "drug_id", "quantity", "dispensed_quantity"),
    "sale": ("sale_id", "sold_at", "branch_id", "employee_id", "customer_id", "prescription_id", "gross_amount",
             "discount_amount"),
    "sale_item": ("sale_id", "sold_at", "line_no", "batch_id", "quantity", "unit_price"),
    "stock": ("branch_id", "batch_id", "quantity"),
    "stock_transfer": ("transfer_id", "from_branch_id", "to_branch_id", "batch_id", "quantity", "employee_id",
                       "transferred_at"),
    "batch_movement": ("movement_id", "batch_id", "branch_id", "quantity_delta", "reason", "reference_id",
                       "occurred_at"),
}

LOAD_ORDER = ("branch", "job_position", "employee", "manufacturer", "category", "drug", "batch", "doctor",
              "customer", "prescription", "prescription_item", "sale", "sale_item", "stock", "stock_transfer",
              "batch_movement")

IDENTITY = {
    "stock_transfer": "transfer_id",
    "branch": "branch_id", "job_position": "position_id", "employee": "employee_id",
    "manufacturer": "manufacturer_id", "category": "category_id", "drug": "drug_id", "batch": "batch_id",
    "doctor": "doctor_id", "customer": "customer_id", "prescription": "prescription_id", "sale": "sale_id",
    "batch_movement": "movement_id",
}


def load(conn: psycopg.Connection[Any], cfg: SeedConfig, fin_key: str, reset: bool = False) -> dict[str, int]:
    """Generate and bulk-load data. Requires a superuser connection (session_replication_role)."""
    existing = conn.execute("SELECT count(*) FROM pharma.branch").fetchone()
    count = next(iter(existing.values())) if isinstance(existing, dict) else existing[0]  # type: ignore[index]
    if count and not reset:
        raise RuntimeError("Domain tables are not empty. Use --reset to replace existing data.")

    gen = Generator(cfg)
    rows = gen.generate()
    counts: dict[str, int] = {}

    with conn.transaction():
        if reset:
            conn.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(sql.Identifier(*t.split(".")) for t in DOMAIN_TABLES)))
            conn.execute("TRUNCATE analytics.fact_sales")
            conn.execute("UPDATE analytics.etl_state SET last_sale_ts = '-infinity', refreshed_at = NULL")
        conn.execute("SELECT pharma.ensure_sale_partitions(%s, %s)", (gen.start, cfg.today))
        conn.execute("SET LOCAL session_replication_role = replica")
        for table in LOAD_ORDER:
            cols = COLUMNS[table]
            stmt = sql.SQL("COPY pharma.{} ({}) FROM STDIN").format(
                sql.Identifier(table), sql.SQL(", ").join(sql.Identifier(c) for c in cols))
            with conn.cursor().copy(stmt) as copy:
                for row in rows[table]:
                    copy.write_row(row)
            counts[table] = len(rows[table])
            log.info("Loaded %-18s %9d rows", table, counts[table])

        conn.execute("CREATE TEMP TABLE seed_fin (customer_id integer PRIMARY KEY, fin text) ON COMMIT DROP")
        with conn.cursor().copy("COPY seed_fin (customer_id, fin) FROM STDIN") as copy:
            for row in gen.fins:
                copy.write_row(row)
        conn.execute(
            """
            UPDATE pharma.customer c
               SET fin_encrypted = pgp_sym_encrypt(f.fin, %(k)s),
                   fin_hash = encode(hmac(f.fin, %(k)s, 'sha256'), 'hex')
              FROM seed_fin f
             WHERE f.customer_id = c.customer_id
            """,
            {"k": fin_key},
        )
        conn.execute("SET LOCAL session_replication_role = origin")

        for table, column in IDENTITY.items():
            conn.execute(
                sql.SQL("SELECT setval(pg_get_serial_sequence({}, {}), greatest(1, coalesce(max({}), 0))) "
                        "FROM pharma.{}")
                .format(sql.Literal(f"pharma.{table}"), sql.Literal(column), sql.Identifier(column),
                        sql.Identifier(table))
            )
    conn.execute("ANALYZE")
    return counts
