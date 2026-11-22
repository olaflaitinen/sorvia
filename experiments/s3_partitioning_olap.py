"""S3: Partition pruning and the star schema.

Part A  pharma.sale (monthly range partitions) against lab.sale_flat, an
        unpartitioned copy with the same indexes, for queries restricted to a
        day, a month and a quarter.

Part B  The same management reports written against the normalised OLTP schema
        and against the analytics star schema.
"""

from __future__ import annotations

import argparse
import sys

from common import connect, measure, out_dir, save_environment, try_plot, write_csv

PARTITION_QUERIES = {
    "1 gün": ("sold_at >= date_trunc('day', now() - interval '20 days') "
              "AND sold_at < date_trunc('day', now() - interval '19 days')"),
    "1 ay": ("sold_at >= date_trunc('month', now() - interval '2 months') "
             "AND sold_at < date_trunc('month', now() - interval '1 month')"),
    "1 rüb": ("sold_at >= date_trunc('quarter', now() - interval '6 months') "
              "AND sold_at < date_trunc('quarter', now() - interval '3 months')"),
}

REPORTS = {
    "Filial üzrə aylıq gəlir": (
        """SELECT s.branch_id, date_trunc('month', s.sold_at AT TIME ZONE 'Asia/Baku') AS m,
                  sum(si.quantity * si.unit_price) FROM pharma.sale_item si
             JOIN pharma.sale s ON s.sale_id = si.sale_id AND s.sold_at = si.sold_at GROUP BY 1, 2""",
        """SELECT f.branch_key, d.year, d.month, sum(f.gross_amount) FROM analytics.fact_sales f
             JOIN analytics.dim_date d ON d.date_key = f.date_key GROUP BY 1, 2, 3""",
    ),
    "Kateqoriya üzrə satış": (
        """SELECT c.name, sum(si.quantity) FROM pharma.sale_item si JOIN pharma.batch b ON b.batch_id = si.batch_id
             JOIN pharma.drug d ON d.drug_id = b.drug_id JOIN pharma.category c ON c.category_id = d.category_id
            GROUP BY 1""",
        """SELECT dd.category_name, sum(f.quantity) FROM analytics.fact_sales f
             JOIN analytics.dim_drug dd ON dd.drug_key = f.drug_key GROUP BY 1""",
    ),
    "Şəhər və ölkə üzrə satış": (
        """SELECT br.city, m.country, sum(si.quantity * si.unit_price) FROM pharma.sale_item si
             JOIN pharma.sale s ON s.sale_id = si.sale_id AND s.sold_at = si.sold_at
             JOIN pharma.branch br ON br.branch_id = s.branch_id JOIN pharma.batch b ON b.batch_id = si.batch_id
             JOIN pharma.drug d ON d.drug_id = b.drug_id
             JOIN pharma.manufacturer m ON m.manufacturer_id = d.manufacturer_id
            GROUP BY 1, 2""",
        """SELECT db.city, dd.manufacturer_country, sum(f.gross_amount) FROM analytics.fact_sales f
             JOIN analytics.dim_branch db ON db.branch_key = f.branch_key
             JOIN analytics.dim_drug dd ON dd.drug_key = f.drug_key GROUP BY 1, 2""",
    ),
    "Həftəsonu payı": (
        """SELECT extract(isodow FROM s.sold_at AT TIME ZONE 'Asia/Baku') IN (6, 7), count(*)
             FROM pharma.sale_item si JOIN pharma.sale s ON s.sale_id = si.sale_id AND s.sold_at = si.sold_at
            GROUP BY 1""",
        """SELECT d.is_weekend, count(*) FROM analytics.fact_sales f
             JOIN analytics.dim_date d ON d.date_key = f.date_key GROUP BY 1""",
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=11)
    args = ap.parse_args()

    out = out_dir("s3_partitioning_olap")
    conn = connect()
    save_environment(out, conn)
    conn.execute("CREATE SCHEMA IF NOT EXISTS lab")
    conn.execute("DROP TABLE IF EXISTS lab.sale_flat")
    conn.execute("CREATE TABLE lab.sale_flat AS SELECT * FROM pharma.sale")
    conn.execute("CREATE INDEX ON lab.sale_flat (branch_id, sold_at)")
    conn.execute("CREATE INDEX ON lab.sale_flat (sold_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS sale_sold_at_idx ON pharma.sale (sold_at)")
    conn.execute("VACUUM ANALYZE lab.sale_flat")
    conn.execute("ANALYZE pharma.sale")

    part_rows = []
    for label, predicate in PARTITION_QUERIES.items():
        for table in ("pharma.sale", "lab.sale_flat"):
            q = f"SELECT count(*), sum(net_amount) FROM {table} WHERE {predicate}"
            m = measure(conn, q, runs=args.runs)
            part_rows.append([label, table, round(m["median_ms"], 3)])
            print(f"A {label:6s} {table:14s} {m['median_ms']:8.3f} ms")
    write_csv(out / "partitioning.csv", ["range", "table", "median_ms"], part_rows)

    olap_rows = []
    for label, (oltp, star) in REPORTS.items():
        m1 = measure(conn, oltp, runs=args.runs)
        m2 = measure(conn, star, runs=args.runs)
        olap_rows.append([label, round(m1["median_ms"], 2), round(m2["median_ms"], 2),
                          round(m1["median_ms"] / m2["median_ms"], 2)])
        print(f"B {label:28s} OLTP {m1['median_ms']:9.2f} ms   star {m2['median_ms']:9.2f} ms")
    write_csv(out / "olap.csv", ["report", "oltp_ms", "star_ms", "speedup"], olap_rows)

    plt = try_plot()
    if plt is not None:
        fig, ax = plt.subplots(figsize=(8, 4))
        labels = [r[0] for r in olap_rows]
        x = range(len(labels))
        ax.bar([i - 0.2 for i in x], [r[1] for r in olap_rows], 0.4, label="3NF (OLTP)", color="#9aa5b1")
        ax.bar([i + 0.2 for i in x], [r[2] for r in olap_rows], 0.4, label="Ulduz sxemi", color="#2f6fde")
        ax.set_xticks(list(x), labels, rotation=12)
        ax.set_ylabel("Median gecikmə (ms)")
        ax.set_title("S3: Hesabatlar, 3NF və ulduz sxemi")
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(out / "s3_olap.png", dpi=160)

    conn.execute("DROP TABLE lab.sale_flat")
    conn.execute("DROP INDEX IF EXISTS pharma.sale_sold_at_idx")
    print(f"Results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
