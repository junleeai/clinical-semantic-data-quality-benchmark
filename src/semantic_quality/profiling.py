"""Export reproducible, identifier-free aggregates from the local DuckDB database."""

import argparse
import json
import logging
import tempfile
from pathlib import Path

import duckdb

from semantic_quality.ingestion import DATABASE, ROOT

SQL = ROOT / "sql"
ANALYTES = ROOT / "configs" / "analytes.csv"
OUTPUT = ROOT / "results" / "profile.json"
QUERIES = ("overview", "missingness", "display_values", "units", "reference_ranges")
LOG = logging.getLogger(__name__)


def collect_profile(database: Path = DATABASE) -> dict:
    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute(
            """
            CREATE TEMP TABLE analytes AS
            SELECT * FROM read_csv(
                ?, header = true,
                columns = {'itemid': 'INTEGER', 'analyte': 'VARCHAR', 'expected_source_unit': 'VARCHAR'}
            )
            """,
            [str(ANALYTES)],
        )
        connection.execute((SQL / "profile_inputs.sql").read_text())
        profile = {
            "dataset": "MIMIC-IV Clinical Database Demo v2.2 (doi:10.13026/dp1f-ex47)",
            "patient_table_count": connection.execute("SELECT count(*) FROM patients").fetchone()[0],
        }
        for name in QUERIES:
            result = connection.execute((SQL / f"{name}.sql").read_text())
            columns = [column[0] for column in result.description]
            profile[name] = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
        return profile


def write_profile(profile: dict, output: Path = OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="profile-", dir=output.parent) as directory:
        staged = Path(directory) / output.name
        staged.write_text(json.dumps(profile, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        staged.replace(output)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        write_profile(collect_profile())
    except (OSError, ValueError, duckdb.Error) as error:
        raise SystemExit(f"Profiling failed: {error}") from None
    LOG.info("Wrote aggregate profile to %s", OUTPUT)


if __name__ == "__main__":
    main()
