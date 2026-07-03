#!/usr/bin/env python3
"""Plot storage usage aggregation from the Parquet ingestion output."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path


os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARQUET_GLOB = REPO_ROOT / "data/storage-usage/**/*.parquet"

QUERY = """
WITH source AS (
    SELECT *
    FROM read_parquet('{parquet_glob}', union_by_name = true)
)
SELECT
    source.period_start,
    source.period_end,
    source.interval_kind,
    source.ConfigName,
    SUM(source.SESize)::DOUBLE AS Value
FROM source
WHERE source.SEName <> 'FakeSE'
  AND source.IsDisk = false
GROUP BY
    source.period_start,
    source.period_end,
    source.interval_kind,
    source.ConfigName
HAVING COUNT(*) >= 1
ORDER BY source.period_start, Value DESC, source.ConfigName
"""


def sql_literal(value: object) -> str:
    return str(value).replace("'", "''")


def duckdb_command(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("duckdb")
    if found:
        return found
    fallback = Path.home() / ".local/bin/duckdb"
    if fallback.exists():
        return str(fallback)
    raise RuntimeError("duckdb CLI not found; pass --duckdb /path/to/duckdb")


def load_query_rows(duckdb: str, parquet_glob: Path | str) -> list[dict[str, str]]:
    query = QUERY.format(parquet_glob=sql_literal(parquet_glob))
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as output:
        output_path = Path(output.name)

    try:
        copy_sql = f"COPY ({query}) TO '{sql_literal(output_path)}' (HEADER, DELIMITER ',');"
        subprocess.run([duckdb, ":memory:", "-c", copy_sql], check=True)
        with output_path.open(newline="") as handle:
            return list(csv.DictReader(handle))
    finally:
        output_path.unlink(missing_ok=True)


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def plot_rows(rows: list[dict[str, str]], output: Path | None) -> None:
    if not rows:
        raise RuntimeError("query returned no rows; ingest Parquet files first")

    interval_kinds = {row["interval_kind"] for row in rows}
    series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for row in rows:
        label = row["ConfigName"]
        if len(interval_kinds) > 1:
            label = f"{label} ({row['interval_kind']})"
        series[label].append((parse_timestamp(row["period_start"]), float(row["Value"])))

    plt.figure(figsize=(14, 7))
    for label, points in sorted(series.items()):
        points.sort(key=lambda item: item[0])
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        plt.plot(x_values, y_values, marker="o", linewidth=1.5, markersize=3, label=label)

    plt.title("Storage Usage by ConfigName")
    plt.xlabel("Snapshot period start")
    plt.ylabel("Total SE size (bytes)")
    plt.legend(title="ConfigName", loc="best", fontsize="small")
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output)
    else:
        plt.show()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb", help="Path to the duckdb CLI")
    parser.add_argument("--parquet-glob", default=str(DEFAULT_PARQUET_GLOB), help="Parquet glob to query")
    parser.add_argument("--output", type=Path, help="Write the plot to an image file instead of showing it")
    args = parser.parse_args()

    duckdb = duckdb_command(args.duckdb)
    rows = load_query_rows(duckdb, args.parquet_glob)
    plot_rows(rows, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
