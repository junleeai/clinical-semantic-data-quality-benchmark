"""Freeze the verified Demo v2.2 numeric cohort and retain its source exclusions."""

import argparse
import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb

from semantic_quality.ingestion import CHECKSUMS, DATABASE, ROOT
from semantic_quality.snapshots import fingerprint, json_bytes, jsonl_bytes, publish_snapshot

CONFIG = ROOT / "configs" / "lab-mappings.csv"
LOCK = ROOT / "configs" / "reference-lock.json"
REFERENCE = ROOT / "data" / "processed" / "reference"
SQL = ROOT / "sql" / "reference_candidates.sql"
LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LabMapping:
    itemid: int
    analyte: str
    source_unit: str
    canonical_unit: str
    loinc: str
    alternate_unit: str
    alternate_loinc: str
    alternate_factor: float
    swap_itemid: int
    wrong_specimen_loinc: str


@dataclass(frozen=True, slots=True)
class Observation:
    labevent_id: int
    subject_id: int
    specimen_id: int
    charttime: str
    itemid: int
    value: float
    unit: str
    loinc: str
    lower_bound: float
    upper_bound: float


def load_mappings() -> dict[int, LabMapping]:
    mappings = {}
    with CONFIG.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            mapping = LabMapping(**{
                **row, "itemid": int(row["itemid"]), "swap_itemid": int(row["swap_itemid"]),
                "alternate_factor": float(row["alternate_factor"]),
            })
            if mapping.itemid in mappings:
                raise ValueError(f"Duplicate lab mapping for {mapping.itemid}")
            mappings[mapping.itemid] = mapping
    return mappings


def extract_reference(database: Path, mappings: dict[int, LabMapping]) -> tuple[tuple[Observation, ...], list[dict]]:
    """Read the source database without modifying it."""
    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute("CREATE TEMP TABLE selected_items (itemid INTEGER PRIMARY KEY)")
        connection.executemany("INSERT INTO selected_items VALUES (?)", [(key,) for key in mappings])
        cursor = connection.execute(SQL.read_text())
        columns = [column[0] for column in cursor.description]
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    cohort = []
    audit = []
    for row in rows:
        mapping = mappings[row["itemid"]]
        if (row["dictionary_label"], row["fluid"], row["category"]) != (mapping.analyte, "Blood", "Chemistry"):
            raise ValueError(f"Unexpected dictionary metadata for {mapping.itemid}")
        if not row["patient_exists"] or any(row[key] is None for key in ("labevent_id", "specimen_id", "charttime")):
            raise ValueError("Candidate reference row has missing identity or sample metadata")
        if not row["finite_numeric"]:
            source_fields = {key: value for key, value in row.items() if key not in {
                "dictionary_label", "fluid", "category", "patient_exists", "finite_numeric",
            }}
            audit.append({
                "disposition": "excluded_nonnumeric",
                "source": {
                    key: value.isoformat() if isinstance(value, (date, datetime)) else value
                    for key, value in source_fields.items()
                },
            })
            continue

        if (row["valueuom"] or "").strip() != mapping.source_unit:
            raise ValueError(f"Unexpected source unit for {mapping.itemid}")
        # Na+ and K+ are monovalent. Their source numbers and bounds carry over unchanged.
        cohort.append(Observation(
            row["labevent_id"], row["subject_id"], row["specimen_id"], row["charttime"].isoformat(),
            mapping.itemid, row["valuenum"], mapping.canonical_unit, mapping.loinc,
            row["ref_range_lower"], row["ref_range_upper"],
        ))
    if len({row.labevent_id for row in cohort} | {row["source"]["labevent_id"] for row in audit}) != len(rows):
        raise ValueError("Candidate reference contains duplicate observation IDs")
    return tuple(cohort), audit


def snapshot_files(database: Path = DATABASE) -> tuple[dict[str, bytes], dict]:
    mappings = load_mappings()
    cohort, audit = extract_reference(database, mappings)
    observations = jsonl_bytes(asdict(row) for row in cohort)
    exclusions = jsonl_bytes(audit)
    metadata = {
        "dataset": "MIMIC-IV Clinical Database Demo v2.2",
        "doi": "10.13026/dp1f-ex47",
        "source_sha256": {name: digest for digest, name in map(str.split, CHECKSUMS.read_text().splitlines())},
        "selection": "Four reviewed item IDs and finite valuenum; use the verified source units.",
        "identity": "labevent_id; retain subject_id and specimen_id; keep repeated results.",
        "specimen_assumption": "Serum or plasma for these routine chemistry item mappings; source fluid is Blood.",
        "numeric_observations": len(cohort),
        "numeric_observations_per_itemid": {
            str(itemid): sum(row.itemid == itemid for row in cohort) for itemid in mappings
        },
        "distinct_patients": len({row.subject_id for row in cohort}),
        "source_audit_observations": len(audit),
        "source_audit_itemids": sorted({row["source"]["itemid"] for row in audit}),
        "canonical_units": {str(itemid): mapping.canonical_unit for itemid, mapping in mappings.items()},
        "canonical_loinc": {str(itemid): mapping.loinc for itemid, mapping in mappings.items()},
        "observations_sha256": fingerprint(observations),
        "source_audit_sha256": fingerprint(exclusions),
    }
    return {
        "observations.jsonl": observations, "source_audit.jsonl": exclusions,
        "metadata.json": json_bytes(metadata, pretty=True),
    }, metadata


def freeze_reference(database: Path = DATABASE, destination: Path = REFERENCE, lock: Path = LOCK) -> dict:
    files, metadata = snapshot_files(database)
    if metadata != json.loads(lock.read_bytes()):
        raise ValueError("Extracted reference differs from the pinned Phase 3 reference")
    publish_snapshot(destination, files)
    return metadata


def read_reference(directory: Path = REFERENCE, lock: Path = LOCK) -> tuple[Observation, ...]:
    metadata = json.loads(lock.read_bytes())
    if json.loads((directory / "metadata.json").read_bytes()) != metadata:
        raise ValueError("Reference metadata differs from its lock")
    observations = (directory / "observations.jsonl").read_bytes()
    source_audit = (directory / "source_audit.jsonl").read_bytes()
    if fingerprint(observations) != metadata["observations_sha256"]:
        raise ValueError("Frozen reference fingerprint mismatch")
    if fingerprint(source_audit) != metadata["source_audit_sha256"]:
        raise ValueError("Frozen source audit fingerprint mismatch")
    return tuple(Observation(**json.loads(line)) for line in observations.splitlines())


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        metadata = freeze_reference()
    except (OSError, ValueError, duckdb.Error) as error:
        raise SystemExit(f"Reference preparation failed: {error}") from None
    LOG.info(
        "Frozen reference: %s numeric observations, %s patients, %s source audit rows",
        metadata["numeric_observations"], metadata["distinct_patients"], metadata["source_audit_observations"],
    )
    LOG.info("Reference SHA-256: %s", metadata["observations_sha256"])


if __name__ == "__main__":
    main()
