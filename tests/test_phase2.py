"""Exercise the pipeline using tiny, fabricated CSV files."""

import csv
import gzip
import hashlib
import json

import duckdb
import pytest

from semantic_quality import ingestion, profiling


def write_table(directory, table, rows, header=None):
    path = directory / f"{table}.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=header or list(ingestion.SCHEMAS[table]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_checksum_rejects_modified_file(tmp_path):
    path = tmp_path / "example.csv.gz"
    path.write_bytes(b"original")
    expected = hashlib.sha256(b"original").hexdigest()

    ingestion.verify_checksum(path, expected)
    path.write_bytes(b"altered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        ingestion.verify_checksum(path, expected)


def test_load_rejects_wrong_header(tmp_path):
    path = write_table(tmp_path, "d_labitems", [], header=["itemid", "label"])
    with duckdb.connect() as connection:
        with pytest.raises(ValueError, match="Unexpected column layout"):
            ingestion.load_table(connection, "d_labitems", path)


@pytest.mark.parametrize("ids", [[1, 1], [1, None]])
def test_load_rejects_duplicate_or_missing_keys(tmp_path, ids):
    path = write_table(tmp_path, "patients", [{"subject_id": key} for key in ids])
    with duckdb.connect() as connection:
        with pytest.raises(ValueError, match="missing or duplicate subject_id"):
            ingestion.load_table(connection, "patients", path)


@pytest.fixture
def staged_inputs(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    write_table(raw, "patients", [{"subject_id": 1}, {"subject_id": 2}])
    write_table(
        raw,
        "d_labitems",
        [{"itemid": 50931, "label": "Glucose", "fluid": "Blood", "category": "Chemistry"}],
    )
    write_table(
        raw,
        "labevents",
        [
            {
                "labevent_id": 1, "subject_id": 1, "itemid": 50931,
                "value": "___", "valuenum": 90, "valueuom": "mg/dL",
                "ref_range_lower": 70, "ref_range_upper": 100,
            },
            {"labevent_id": 2, "subject_id": 1, "itemid": 50931, "valueuom": "mg/dL"},
            {
                "labevent_id": 3, "subject_id": 2, "itemid": 50931,
                "valuenum": "Inf", "valueuom": "   ",
                "ref_range_lower": 100, "ref_range_upper": 70,
            },
            {"labevent_id": 4, "subject_id": 2, "itemid": 99999, "valuenum": 9},
        ],
    )
    manifest = tmp_path / "checksums"
    manifest.write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(raw.glob("*.gz"))
    ))
    monkeypatch.setattr(ingestion, "CHECKSUMS", manifest)
    return raw, tmp_path / "processed" / "mimic.duckdb"


def test_aggregate_profile_preserves_counts_and_excludes_patient_keys(staged_inputs, tmp_path):
    raw, database = staged_inputs
    ingestion.build_database(raw, database)
    profile = profiling.collect_profile(database)
    glucose = next(row for row in profile["overview"] if row["analyte"] == "Glucose")
    assert profile["patient_table_count"] == 2
    assert len(profile["overview"]) == 4
    assert glucose["observations"] == 3
    assert glucose["valid_numeric_observations"] == 1
    assert glucose["nonfinite_numeric"] == 1
    assert glucose["patients_with_observations"] == 2
    assert glucose["patients_with_numeric"] == 1
    assert glucose["median_per_patient"] == 1.5

    assert {row["unit"]: row["observations"] for row in profile["units"]} == {"mg/dL": 2, None: 1}
    assert {row["range_status"] for row in profile["reference_ranges"]} == {
        "complete and ordered", "reversed", "missing both",
    }
    assert profile["display_values"][0]["masked_display_values_with_valid_numeric"] == 1
    missing_numeric = next(row for row in profile["missingness"] if row["field"] == "valuenum")
    assert missing_numeric["missing_observations"] == 1

    output = tmp_path / "results" / "profile.json"
    profiling.write_profile(profile, output)
    assert json.loads(output.read_text()) == profile
    for section in profiling.QUERIES:
        for row in profile[section]:
            assert {"labevent_id", "subject_id", "hadm_id", "specimen_id"}.isdisjoint(row)


def test_failed_rebuild_preserves_previous_database(staged_inputs, monkeypatch):
    raw, database = staged_inputs
    ingestion.build_database(raw, database)
    original = database.read_bytes()
    actual_load = ingestion.load_table

    def fail_on_patients(connection, table, path):
        if table == "patients":
            raise ValueError("simulated parse failure")
        return actual_load(connection, table, path)

    monkeypatch.setattr(ingestion, "load_table", fail_on_patients)
    with pytest.raises(ValueError, match="simulated parse failure"):
        ingestion.build_database(raw, database)
    assert database.read_bytes() == original
    assert list(database.parent.iterdir()) == [database]


def test_download_promotes_only_verified_bytes(tmp_path, monkeypatch):
    from io import BytesIO

    raw = tmp_path / "raw"
    name = "patients.csv.gz"
    expected = hashlib.sha256(b"official bytes").hexdigest()
    monkeypatch.setattr(ingestion, "urlopen", lambda *_args, **_kwargs: BytesIO(b"bad bytes"))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        ingestion.download_file(raw, name, expected)
    assert list(raw.iterdir()) == []

    def official_response(url, timeout):
        assert url == f"{ingestion.SOURCE}/{name}"
        return BytesIO(b"official bytes")

    monkeypatch.setattr(ingestion, "urlopen", official_response)
    ingestion.download_file(raw, name, expected)
    assert (raw / name).read_bytes() == b"official bytes"
