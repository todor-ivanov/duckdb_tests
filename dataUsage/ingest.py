#!/usr/bin/env python3
"""Convert LHCb storage CSV snapshots into typed Parquet files.

The dataset manifest contains daily and weekly CSV/ZST files. Their filenames
define the time interval covered by the snapshot:

* storage-YYYY-MM-DD.csv.zst -> [YYYY-MM-DD, YYYY-MM-DD + 1 day)
* storage-YYYY-WW.csv.zst    -> ISO week [Monday, next Monday)
* storage-occupancy-YYYY-MM-DD.csv.zst -> [YYYY-MM-DD, YYYY-MM-DD + 1 day)

Every exported Parquet row gets interval metadata so downstream queries can
recreate the OpenSearch time bucket without hardcoding bucket values.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen


BASE_URL = "https://lhcbdirac.s3.cern.ch/"

STORAGE_USAGE_COLUMNS_SQL = """
{
    'SEName': VARCHAR,
    'Name': VARCHAR,
    'SESize': BIGINT,
    'SEFiles': BIGINT,
    'SESite': VARCHAR,
    'SEType': VARCHAR,
    'IsDisk': BOOLEAN,
    'production': DOUBLE,
    'filetype': VARCHAR,
    'online_stream': VARCHAR,
    'maybe_eventtype': DOUBLE,
    'ConfigName': VARCHAR,
    'ConfigVersion': VARCHAR,
    'Description': VARCHAR,
    'ProcPath': VARCHAR,
    'EventTypeID': DOUBLE
}
""".strip()

STORAGE_OCCUPANCY_COLUMNS_SQL = """
{
    'SpaceReservation': VARCHAR,
    'Total': BIGINT,
    'Free': BIGINT,
    'Site': VARCHAR
}
""".strip()


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    manifest_url: str
    filename_prefix: str
    columns_sql: str


DATASETS = {
    "storage-usage": DatasetConfig(
        name="storage-usage",
        manifest_url=BASE_URL + "storage-usage/storage-list.json",
        filename_prefix="storage",
        columns_sql=STORAGE_USAGE_COLUMNS_SQL,
    ),
    "storage-occupancy": DatasetConfig(
        name="storage-occupancy",
        manifest_url=BASE_URL + "storage-occupancy/storage-occupancy-list.json",
        filename_prefix="storage-occupancy",
        columns_sql=STORAGE_OCCUPANCY_COLUMNS_SQL,
    ),
}


@dataclass(frozen=True)
class Snapshot:
    manifest_path: str
    local_path: Path
    parquet_path: Path
    interval_kind: str
    period_start: datetime
    period_end: datetime
    snapshot_time: datetime


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def sql_timestamp(value: datetime) -> str:
    return sql_literal(value.replace(tzinfo=None).isoformat(sep=" "))


def parquet_path_for(download_dir: Path, manifest_path: str) -> Path:
    relative = Path(manifest_path)
    if relative.name.endswith(".csv.zst"):
        name = relative.name.removesuffix(".csv.zst") + ".parquet"
    elif relative.name.endswith(".csv"):
        name = relative.name.removesuffix(".csv") + ".parquet"
    else:
        name = relative.stem + ".parquet"
    return download_dir / relative.parent / name


def parse_snapshot_path(
    manifest_path: str,
    interval_kind: str,
    dataset: DatasetConfig,
    creation_time: str | None = None,
) -> tuple[datetime, datetime, datetime]:
    name = Path(manifest_path).name
    prefix = re.escape(dataset.filename_prefix)
    daily = re.fullmatch(
        rf"{prefix}-(\d{{4}})-(\d{{2}})-(\d{{2}})\.csv(?:\.zst)?",
        name,
    )
    if daily:
        start_date = date(int(daily.group(1)), int(daily.group(2)), int(daily.group(3)))
        start = datetime.combine(start_date, time.min)
        end = start + timedelta(days=1)
        return start, end, end

    weekly = re.fullmatch(rf"{prefix}-(\d{{4}})-(\d{{1,2}})\.csv(?:\.zst)?", name)
    if weekly:
        start_date = date.fromisocalendar(int(weekly.group(1)), int(weekly.group(2)), 1)
        start = datetime.combine(start_date, time.min)
        end = start + timedelta(days=7)
        return start, end, end

    if interval_kind == "latest" and creation_time:
        instant = (
            datetime.fromisoformat(creation_time.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        return instant, instant, instant

    raise ValueError(f"cannot derive interval from {manifest_path!r}")


def parse_filter_bound(value: str) -> datetime:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        parsed_date = date.fromisoformat(value)
        return datetime.combine(parsed_date, time.min)

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def filter_snapshots(
    snapshots: list[Snapshot],
    from_time: datetime | None,
    to_time: datetime | None,
) -> list[Snapshot]:
    if from_time is not None and to_time is not None and from_time >= to_time:
        raise ValueError("--from-date must be earlier than --to-date")

    filtered = []
    for snapshot in snapshots:
        starts_before_to = to_time is None or snapshot.period_start < to_time
        ends_after_from = from_time is None or snapshot.period_end > from_time
        if starts_before_to and ends_after_from:
            filtered.append(snapshot)
    return filtered


def manifest_snapshots(
    manifest: dict,
    download_dir: Path,
    include_latest: bool,
    granularity: str,
    dataset: DatasetConfig,
) -> list[Snapshot]:
    snapshots: list[Snapshot] = []
    interval_kinds = ("weekly", "daily") if granularity == "all" else (granularity,)

    for interval_kind in interval_kinds:
        for manifest_path in manifest.get(interval_kind, []):
            start, end, snapshot_time = parse_snapshot_path(
                manifest_path,
                interval_kind,
                dataset,
            )
            snapshots.append(
                Snapshot(
                    manifest_path=manifest_path,
                    local_path=download_dir / manifest_path,
                    parquet_path=parquet_path_for(download_dir, manifest_path),
                    interval_kind=interval_kind,
                    period_start=start,
                    period_end=end,
                    snapshot_time=snapshot_time,
                )
            )

    if include_latest and manifest.get("latest"):
        latest = manifest["latest"]
        manifest_path = latest["filename"]
        start, end, snapshot_time = parse_snapshot_path(
            manifest_path,
            "latest",
            dataset,
            latest.get("creation_time"),
        )
        snapshots.append(
            Snapshot(
                manifest_path=manifest_path,
                local_path=download_dir / manifest_path,
                parquet_path=parquet_path_for(download_dir, manifest_path),
                interval_kind="latest",
                period_start=start,
                period_end=end,
                snapshot_time=snapshot_time,
            )
        )

    return snapshots


def local_snapshots(paths: list[Path], dataset: DatasetConfig) -> list[Snapshot]:
    snapshots: list[Snapshot] = []
    for path in paths:
        prefix = re.escape(dataset.filename_prefix)
        interval_kind = (
            "weekly"
            if re.fullmatch(rf"{prefix}-\d{{4}}-\d{{1,2}}\.csv(?:\.zst)?", path.name)
            else "daily"
        )
        start, end, snapshot_time = parse_snapshot_path(path.name, interval_kind, dataset)
        snapshots.append(
            Snapshot(
                manifest_path=path.name,
                local_path=path,
                parquet_path=parquet_path_for(path.parent, path.name),
                interval_kind=interval_kind,
                period_start=start,
                period_end=end,
                snapshot_time=snapshot_time,
            )
        )
    return snapshots


def load_manifest(url: str) -> dict:
    with urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def download_snapshot(snapshot: Snapshot, force: bool) -> None:
    if snapshot.local_path.exists() and not force:
        return

    snapshot.local_path.parent.mkdir(parents=True, exist_ok=True)
    url = BASE_URL + snapshot.manifest_path
    tmp_path = snapshot.local_path.with_suffix(snapshot.local_path.suffix + ".part")
    with urlopen(url, timeout=300) as response, tmp_path.open("wb") as out:
        shutil.copyfileobj(response, out)
    tmp_path.replace(snapshot.local_path)


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


def run_duckdb(duckdb: str, sql: str) -> None:
    subprocess.run([duckdb, ":memory:", "-c", sql], check=True)


def convert_snapshot(
    duckdb: str,
    snapshot: Snapshot,
    force: bool,
    dataset: DatasetConfig,
) -> None:
    if snapshot.parquet_path.exists() and not force:
        return

    snapshot.parquet_path.parent.mkdir(parents=True, exist_ok=True)
    read_csv = f"""
read_csv(
    {sql_literal(snapshot.local_path)},
    delim = ',',
    header = true,
    columns = {dataset.columns_sql},
    ignore_errors = true
)
""".strip()

    sql = f"""
COPY (
SELECT
    {sql_literal(snapshot.manifest_path)} AS source_path,
    {sql_literal(Path(snapshot.manifest_path).name)} AS source_filename,
    {sql_literal(snapshot.interval_kind)} AS interval_kind,
    {sql_timestamp(snapshot.period_start)}::TIMESTAMP AS period_start,
    {sql_timestamp(snapshot.period_end)}::TIMESTAMP AS period_end,
    {sql_timestamp(snapshot.snapshot_time)}::TIMESTAMP AS snapshot_time,
    *
FROM {read_csv}
) TO {sql_literal(snapshot.parquet_path)} (FORMAT PARQUET);
"""
    run_duckdb(duckdb, sql)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-dir", default="data", type=Path)
    parser.add_argument(
        "--dataset",
        choices=tuple(DATASETS),
        default="storage-usage",
        help="Dataset manifest/schema to ingest",
    )
    parser.add_argument("--manifest-url", help="Override the selected dataset manifest URL")
    parser.add_argument("--duckdb", help="Path to the duckdb CLI")
    parser.add_argument(
        "--granularity",
        choices=("all", "daily", "weekly"),
        default="all",
        help="Manifest interval granularity to ingest",
    )
    parser.add_argument("--include-latest", action="store_true", help="Also ingest the rolling latest file")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--overwrite-parquet", action="store_true")
    parser.add_argument(
        "--from-date",
        help="Include snapshots whose interval overlaps this inclusive lower bound, e.g. 2026-01-01",
    )
    parser.add_argument(
        "--to-date",
        help="Include snapshots whose interval overlaps this exclusive upper bound, e.g. 2026-02-01",
    )
    parser.add_argument("--limit", type=int, help="Ingest only the first N snapshots after manifest expansion")
    parser.add_argument(
        "--local-files",
        nargs="*",
        type=Path,
        help="Ingest explicit local CSV/CSV.ZST files instead of fetching the manifest",
    )
    args = parser.parse_args()

    dataset = DATASETS[args.dataset]
    manifest_url = args.manifest_url or dataset.manifest_url
    duckdb = duckdb_command(args.duckdb)

    if args.local_files is not None:
        snapshots = local_snapshots(args.local_files, dataset)
    else:
        manifest = load_manifest(manifest_url)
        snapshots = manifest_snapshots(
            manifest,
            args.download_dir,
            args.include_latest,
            args.granularity,
            dataset,
        )

    snapshots.sort(key=lambda item: (item.period_start, item.period_end, item.manifest_path))
    from_time = parse_filter_bound(args.from_date) if args.from_date else None
    to_time = parse_filter_bound(args.to_date) if args.to_date else None
    snapshots = filter_snapshots(snapshots, from_time, to_time)
    if args.limit is not None:
        snapshots = snapshots[: args.limit]

    for index, snapshot in enumerate(snapshots, start=1):
        if args.local_files is None:
            download_snapshot(snapshot, args.force_download)
        print(f"[{index}/{len(snapshots)}] writing {snapshot.parquet_path}", flush=True)
        convert_snapshot(duckdb, snapshot, args.overwrite_parquet, dataset)

    print(f"converted {len(snapshots)} snapshot(s) to parquet", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"duckdb command failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode)
