"""Fetch and load the three official MIMIC-IV Demo v2.2 tables."""

import argparse
import csv
import gzip
import hashlib
import logging
import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen

import duckdb

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DATABASE = ROOT / "data" / "processed" / "mimic.duckdb"
CHECKSUMS = ROOT / "configs" / "physionet-v2.2.sha256"
SOURCE = "https://physionet.org/files/mimic-iv-demo/2.2/hosp"
LOG = logging.getLogger(__name__)

SCHEMAS = {
    "labevents": {
        "labevent_id": "BIGINT",
        "subject_id": "BIGINT",
        "hadm_id": "BIGINT",
        "specimen_id": "BIGINT",
        "itemid": "INTEGER",
        "order_provider_id": "VARCHAR",
        "charttime": "TIMESTAMP",
        "storetime": "TIMESTAMP",
        "value": "VARCHAR",
        "valuenum": "DOUBLE",
        "valueuom": "VARCHAR",
        "ref_range_lower": "DOUBLE",
        "ref_range_upper": "DOUBLE",
        "flag": "VARCHAR",
        "priority": "VARCHAR",
        "comments": "VARCHAR",
    },
    "d_labitems": {
        "itemid": "INTEGER",
        "label": "VARCHAR",
        "fluid": "VARCHAR",
        "category": "VARCHAR",
    },
    "patients": {
        "subject_id": "BIGINT",
        "gender": "VARCHAR",
        "anchor_age": "INTEGER",
        "anchor_year": "INTEGER",
        "anchor_year_group": "VARCHAR",
        "dod": "DATE",
    },
}

KEYS = {
    "labevents": "labevent_id",
    "d_labitems": "itemid",
    "patients": "subject_id",
}


def verify_checksum(path: Path, expected_hash: str) -> None:
    with path.open("rb") as source:
        actual_hash = hashlib.file_digest(source, "sha256").hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f"SHA-256 mismatch for {path.name}: found {actual_hash}")


def download_file(raw_dir: Path, name: str, expected_hash: str) -> None:
    destination = raw_dir / name
    if destination.exists():
        return  # An existing file will be verified along with the rest of the inputs.

    raw_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="download-", dir=raw_dir) as temporary_dir:
        staged = Path(temporary_dir) / name
        with urlopen(f"{SOURCE}/{name}", timeout=30) as response, staged.open("wb") as output:
            shutil.copyfileobj(response, output)
        verify_checksum(staged, expected_hash)
        staged.replace(destination)


def load_table(connection: duckdb.DuckDBPyConnection, table: str, path: Path) -> int:
    schema = SCHEMAS[table]
    with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
        header = next(csv.reader(source), [])
    if header != list(schema):
        raise ValueError(f"Unexpected column layout for {table}")

    # Load with declared types so a sample of CSV rows cannot change the schema.
    connection.execute(
        f"""
        CREATE TABLE {table} AS
        SELECT * FROM read_csv(
            ?, columns = ?, header = true, auto_detect = false,
            delim = ',', quote = '"', escape = '"', strict_mode = true
        )
        """,
        [str(path), schema],
    )
    key = KEYS[table]
    rows, distinct_keys = connection.execute(
        f"SELECT count(*), count(DISTINCT {key}) FROM {table}"
    ).fetchone()
    if rows == 0 or rows != distinct_keys:
        raise ValueError(f"{table} is empty or has missing or duplicate {key} values")
    return rows


def build_database(
    raw_dir: Path = RAW,
    database: Path = DATABASE,
    *,
    allow_download: bool = False,
) -> None:
    checksums = {name: digest for digest, name in map(str.split, CHECKSUMS.read_text().splitlines())}
    for table in SCHEMAS:
        name = f"{table}.csv.gz"
        if allow_download:
            download_file(raw_dir, name, checksums[name])
        verify_checksum(raw_dir / name, checksums[name])
        LOG.info("Verified SHA-256 for %s", name)

    database.parent.mkdir(parents=True, exist_ok=True)
    # Replace the previous database only after the entire new one has loaded.
    with tempfile.TemporaryDirectory(prefix="ingestion-", dir=database.parent) as directory:
        staged = Path(directory) / database.name
        with duckdb.connect(str(staged)) as connection:
            for table in SCHEMAS:
                rows = load_table(connection, table, raw_dir / f"{table}.csv.gz")
                LOG.info("Loaded %s with %s rows", table, f"{rows:,}")
        staged.replace(database)
    LOG.info("Wrote local DuckDB database to %s", database)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Fetch any missing official files.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        build_database(allow_download=args.download)
    except (OSError, ValueError, duckdb.Error) as error:
        parser.exit(1, f"Ingestion failed: {error}\n")


if __name__ == "__main__":
    main()
