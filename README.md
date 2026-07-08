# DuckDB tests

Small DuckDB experiments for LHCb/DIRAC data. The repository currently has two
workflows:

- LHCb storage snapshot ingestion and plotting under `dataUsage/`.
- Synthetic pilot data generation and aggregation in the repository root.

## Requirements

- Python 3.10 or newer.
- DuckDB CLI available as `duckdb`, `~/.local/bin/duckdb`, or passed with
  `--duckdb /path/to/duckdb`.
- Python packages used by the scripts:
  - `matplotlib` for plotting.
  - `duckdb`, `polars`, and `numpy` for the synthetic pilot generator.

The storage ingestion script uses only the Python standard library plus the
DuckDB CLI.

## Storage datasets

`dataUsage/ingest.py` supports two LHCb S3-backed datasets.

### `storage-usage`

This is the default dataset. The manifest is:

```text
https://lhcbdirac.s3.cern.ch/storage-usage/storage-list.json
```

Rows describe storage usage grouped by storage element and bookkeeping-like
attributes. The typed CSV schema includes fields such as `SEName`, `Name`,
`SESize`, `SEFiles`, `SESite`, `SEType`, `IsDisk`, `ConfigName`,
`ConfigVersion`, `Description`, `ProcPath`, and `EventTypeID`.

This dataset is what `dataUsage/aggregation.py` plots by default.

### `storage-occupancy`

This dataset comes from:

```text
https://lhcbdirac.s3.cern.ch/storage-occupancy/storage-occupancy-list.json
```

Rows describe space reservation occupancy. The typed CSV schema is:

```text
SpaceReservation, Total, Free, Site
```

It uses the same ingestion machinery as `storage-usage`: manifest expansion,
download, interval parsing, filtering, and per-snapshot Parquet output. The
current plotting script is not written for this schema, so query or plot these
Parquet files with a custom DuckDB query.

## Storage ingestion

The examples below assume they are run from the directory that contains this
repository, so paths start with `duckdb_tests/` and default outputs go under
the sibling `data/` directory. In this workspace that parent directory is
`DuckDB/`.

The default command ingests all daily and weekly `storage-usage` snapshots:

```bash
python3 duckdb_tests/dataUsage/ingest.py
```

Select the dataset explicitly:

```bash
python3 duckdb_tests/dataUsage/ingest.py --dataset storage-usage
python3 duckdb_tests/dataUsage/ingest.py --dataset storage-occupancy
```

Select snapshot granularity:

```bash
python3 duckdb_tests/dataUsage/ingest.py --granularity weekly
python3 duckdb_tests/dataUsage/ingest.py --granularity daily
python3 duckdb_tests/dataUsage/ingest.py --granularity all
```

Ingest a date range. `--from-date` is inclusive, `--to-date` is exclusive, and
snapshots are selected when their interval overlaps the requested range.

```bash
python3 duckdb_tests/dataUsage/ingest.py --from-date 2026-01-01 --to-date 2026-07-01

python3 duckdb_tests/dataUsage/ingest.py \
  --dataset storage-occupancy \
  --granularity weekly \
  --from-date 2026-06-01 \
  --to-date 2026-07-07
```

Limit the number of selected snapshots after manifest expansion and filtering:

```bash
python3 duckdb_tests/dataUsage/ingest.py --dataset storage-occupancy --granularity daily --limit 3
```

Also ingest the rolling `latest` file when the manifest provides one:

```bash
python3 duckdb_tests/dataUsage/ingest.py --include-latest
python3 duckdb_tests/dataUsage/ingest.py --dataset storage-occupancy --include-latest
```

Use a non-default manifest URL:

```bash
python3 duckdb_tests/dataUsage/ingest.py --manifest-url https://example.org/storage-list.json
```

Use a specific DuckDB CLI:

```bash
python3 duckdb_tests/dataUsage/ingest.py --duckdb /path/to/duckdb
```

Redownload CSV/ZST inputs that already exist:

```bash
python3 duckdb_tests/dataUsage/ingest.py --force-download
```

Regenerate Parquet files that already exist:

```bash
python3 duckdb_tests/dataUsage/ingest.py --overwrite-parquet
```

Write downloads and Parquet files to another root directory:

```bash
python3 duckdb_tests/dataUsage/ingest.py --download-dir /tmp/lhcb-storage
```

Ingest explicit local files instead of loading a manifest:

```bash
python3 duckdb_tests/dataUsage/ingest.py \
  --dataset storage-usage \
  --local-files storage-2026-04-09.csv.zst

python3 duckdb_tests/dataUsage/ingest.py \
  --dataset storage-occupancy \
  --local-files storage-occupancy-2026-07-08.csv.zst
```

By default, manifest paths are preserved below the selected download directory.
Examples:

```text
data/storage-usage/weekly/storage-2026-22.parquet
data/storage-occupancy/daily/storage-occupancy-2026-07-08.parquet
```

Every exported row has these metadata columns prepended:

```text
source_path, source_filename, interval_kind, period_start, period_end, snapshot_time
```

## Storage usage plotting

`dataUsage/aggregation.py` plots `storage-usage` Parquet files. It sums
`SESize` by `ConfigName` over the snapshot period, excluding `FakeSE` and rows
where `IsDisk` is true.

Display the plot interactively:

```bash
python3 duckdb_tests/dataUsage/aggregation.py
```

Save the plot to a file:

```bash
python3 duckdb_tests/dataUsage/aggregation.py --output storage_usage.png
```

Query a custom Parquet glob:

```bash
python3 duckdb_tests/dataUsage/aggregation.py \
  --parquet-glob 'data/storage-usage/weekly/*.parquet'
```

Use a specific DuckDB CLI:

```bash
python3 duckdb_tests/dataUsage/aggregation.py --duckdb /path/to/duckdb
```

## Querying storage occupancy

The occupancy dataset can be queried directly with DuckDB after ingestion:

```bash
duckdb :memory: -c "
SELECT
  period_start,
  Site,
  SpaceReservation,
  SUM(Total) AS total_bytes,
  SUM(Free) AS free_bytes
FROM read_parquet('data/storage-occupancy/**/*.parquet', union_by_name = true)
GROUP BY period_start, Site, SpaceReservation
ORDER BY period_start, Site, SpaceReservation;
"
```

## Synthetic pilot data

`generate_test_data.py` creates a large synthetic pilot dataset in DuckDB and
exports it as Parquet under `pilots/`.

```bash
python3 duckdb_tests/generate_test_data.py
```

The generator currently creates `50_000_000` rows over about 700 days, with
weighted distributions for status, cores, memory, and timestamps.

`aggregations.py` reads the exported pilot Parquet files, counts running pilots
in 15-minute time buckets grouped by core count, and shows a Matplotlib plot:

```bash
python3 duckdb_tests/aggregations.py
```

The SQL files in `pilots/` describe and reload the exported schema:

```bash
duckdb pilots.duckdb < duckdb_tests/pilots/schema.sql
duckdb pilots.duckdb < duckdb_tests/pilots/load.sql
```
