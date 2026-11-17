"""Check reference protection and corruption behavior on fabricated laboratory events."""

import json
from dataclasses import FrozenInstanceError, asdict, replace
from decimal import Decimal

import duckdb
import pytest

from semantic_quality import corruption, reference
from semantic_quality.ingestion import load_table
from semantic_quality.snapshots import json_bytes, jsonl_bytes, publish_snapshot
from test_phase2 import write_table


@pytest.fixture
def mappings():
    return reference.load_mappings()


@pytest.fixture
def observations(mappings):
    values = {50912: (0.9, 0.5, 1.2), 50931: (90.0, 70.0, 100.0),
              50971: (4.0, 3.3, 5.1), 50983: (140.0, 133.0, 145.0)}
    rows = []
    for patient in range(1, 9):
        for occurrence in range(3):
            for itemid, mapping in mappings.items():
                value, lower, upper = values[itemid]
                rows.append(reference.Observation(
                    len(rows) + 1, patient, patient * 10 + occurrence, "2100-01-01T00:00:00",
                    itemid, value, mapping.canonical_unit, mapping.loinc, lower, upper,
                ))
    return tuple(rows)


def settings(scenario, rate, seed=42, controls="0"):
    return corruption.RunSettings(scenario, seed, Decimal(rate), Decimal(controls), 4)


def jsonl(files, path):
    return [json.loads(line) for line in files[path].splitlines()]


def outputs(files):
    return jsonl(files, "validator_input/observations.jsonl")


def truth(files):
    return jsonl(files, "ground_truth/observation_changes.jsonl")


@pytest.mark.parametrize("scenario", ["A", "B", "C"])
def test_zero_rate_preserves_records_and_creates_no_errors(observations, mappings, scenario):
    files, summary = corruption.generate_run(observations, mappings, settings(scenario, "0"))
    assert [{key: value for key, value in row.items() if key != "batch_id"}
            for row in outputs(files)] == [asdict(row) for row in observations]
    assert truth(files) == []
    assert files["ground_truth/mapping_changes.jsonl"] == b""
    assert summary["observations_missing_from_output"] == summary["affected_observations"] == 0


@pytest.mark.parametrize("scenario", ["A", "B", "C"])
def test_seeded_runs_are_reproducible_and_differ_between_seeds(observations, mappings, scenario):
    run = settings(scenario, "0.5")
    files, summary = corruption.generate_run(observations, mappings, run)
    assert (files, summary) == corruption.generate_run(tuple(reversed(observations)), mappings, run)
    new_files, _ = corruption.generate_run(observations, mappings, replace(run, seed=13))
    assert {row["labevent_id"] for row in truth(files)} != {
        row["labevent_id"] for row in truth(new_files)
    }
    assert files["validator_input/source_aware/upstream_inventory.jsonl"] == new_files[
        "validator_input/source_aware/upstream_inventory.jsonl"
    ]


@pytest.mark.parametrize("subtype,scale,unit,loinc,bound_scale", [
    ("label_only", 1, "mmol/L", "2345-7", 1),
    ("value_only", 0.05551, "mg/dL", "2345-7", 1),
    ("stale_label", 0.05551, "mg/dL", "2345-7", 0.05551),
    ("wrong_factor", 0.05551 * 1.10, "mmol/L", "14749-6", 0.05551),
    ("correct_conversion", 0.05551, "mmol/L", "14749-6", 0.05551),
])
def test_glucose_unit_operations(observations, mappings, subtype, scale, unit, loinc, bound_scale):
    original = next(row for row in observations if row.itemid == 50931)
    changed = corruption.apply_unit_change(original, mappings[50931], subtype)
    assert changed.value == pytest.approx(original.value * scale)
    assert changed.lower_bound == pytest.approx(original.lower_bound * bound_scale)
    assert changed.upper_bound == pytest.approx(original.upper_bound * bound_scale)
    assert (changed.unit, changed.loinc) == (unit, loinc)
    if subtype == "wrong_factor":
        assert changed.lower_bound < changed.value < changed.upper_bound


def test_creatinine_and_monovalent_controls(observations, mappings):
    for itemid in (50912, 50971, 50983):
        row = next(row for row in observations if row.itemid == itemid)
        subtype = "correct_conversion" if itemid == 50912 else "equivalent_unit"
        converted = corruption.apply_unit_change(row, mappings[itemid], subtype)
        if itemid == 50912:
            assert (converted.unit, converted.loinc) == ("umol/L", "14682-9")
            assert converted.value == pytest.approx(row.value * 88.4)
        else:
            assert converted == replace(row, unit="mEq/L")


def test_unit_manifest_matches_actual_changes_and_keeps_clean_controls(observations, mappings):
    before = jsonl_bytes(asdict(row) for row in observations)
    files, summary = corruption.generate_run(observations, mappings, settings("A", "0.5", controls="0.25"))
    run_truth = {row["labevent_id"]: row for row in truth(files)}
    assert len(run_truth) == len(truth(files))
    assert set(summary["observations_by_subtype"]) == set(corruption.UNIT_ERRORS) | {
        "correct_conversion", "equivalent_unit",
    }
    for original, updated in zip(observations, outputs(files), strict=True):
        assert all(updated[key] == getattr(original, key) for key in (
            "labevent_id", "subject_id", "specimen_id", "charttime", "itemid",
        ))
        observed_changes = {key: updated[key] for key in corruption.observation_payload(original)}
        entry = run_truth.get(original.labevent_id)
        if entry:
            assert entry["original"] == corruption.observation_payload(original)
            assert entry["original"] != entry["corrupted"] == observed_changes
            assert entry["is_error"] == (entry["subtype"] in corruption.UNIT_ERRORS)
            assert (entry["scenario"], entry["seed"], entry["batch_id"]) == ("A", 42, updated["batch_id"])
        else:
            assert observed_changes == corruption.observation_payload(original)
    assert before == jsonl_bytes(asdict(row) for row in observations)
    with pytest.raises(FrozenInstanceError):
        observations[0].value = 0


def test_mapping_errors_change_entire_batch_item_and_preserve_source_id(observations, mappings):
    files, summary = corruption.generate_run(observations, mappings, settings("B", "0.5"))
    changes = {(row["batch_id"], row["itemid"]): row
               for row in jsonl(files, "ground_truth/mapping_changes.jsonl")}
    feed = {(row["batch_id"], row["itemid"]): row["loinc"]
            for row in jsonl(files, "validator_input/source_aware/feed_mappings.jsonl")}
    affected = set()
    for original, updated in zip(observations, outputs(files), strict=True):
        key = updated["batch_id"], updated["itemid"]
        entry = changes.get(key)
        if entry:
            mapping = mappings[original.itemid]
            if entry["subtype"] == "same_unit_analyte_swap":
                alternate = mappings[mapping.swap_itemid]
                assert alternate.canonical_unit == mapping.canonical_unit
                expected_loinc = alternate.loinc
            else:
                expected_loinc = mapping.wrong_specimen_loinc
            assert updated["loinc"] == entry["corrupted"]["loinc"] == feed[key] == expected_loinc
            assert entry["is_error"] and entry["original"]["loinc"] == original.loinc
            affected.add(original.labevent_id)
        assert {key: value for key, value in updated.items() if key != "batch_id"} == asdict(
            replace(original, loinc=updated["loinc"])
        )
    assert affected == {row["labevent_id"] for row in truth(files) if row["is_error"]}
    assert len(changes) == summary["mapping_entries_changed"] == 8
    assert len(affected) == summary["affected_observations"] == 48


def test_missing_mapping_preserves_upstream_and_each_analyte_even_at_max_rate(observations, mappings):
    files, summary = corruption.generate_run(observations, mappings, settings("C", "1"))
    inventory = jsonl(files, "validator_input/source_aware/upstream_inventory.jsonl")
    retained = outputs(files)
    keys = {(row["batch_id"], row["itemid"]) for row in retained}
    assert {itemid for _, itemid in keys} == set(mappings)
    assert len(keys) == len(mappings)
    assert len({(row["subject_id"], row["batch_id"]) for row in inventory}) == 8
    assert [(row["labevent_id"], row["subject_id"]) for row in inventory] == [
        (row.labevent_id, row.subject_id) for row in observations
    ]
    missing = {row["labevent_id"] for row in inventory} - {row["labevent_id"] for row in retained}
    assert missing == {row["labevent_id"] for row in truth(files)
                       if row["is_error"] and row["corrupted"] is None}
    assert len(missing) == summary["observations_missing_from_output"] == 72
    assert summary["mapping_entries_changed"] == 12
    forbidden = {"scenario", "seed", "subtype", "is_error", "original", "corrupted"}
    for name in files:
        if name.startswith("validator_input/"):
            assert all(forbidden.isdisjoint(row) for row in jsonl(files, name))


def test_frozen_snapshot_preserves_source_audit_and_rejects_tampering(tmp_path):
    database = tmp_path / "source.duckdb"
    potassium_event = {
        "subject_id": 1, "specimen_id": 1, "charttime": "2100-01-01 00:00:00",
        "itemid": 50971, "valueuom": "mEq/L", "ref_range_lower": 3.3, "ref_range_upper": 5.1,
    }
    with duckdb.connect(str(database)) as conn:
        source = {
            "patients": [{"subject_id": 1}],
            "d_labitems": [{"itemid": 50971, "label": "Potassium", "fluid": "Blood", "category": "Chemistry"}],
            "labevents": [
                {**potassium_event, "labevent_id": 1, "valuenum": 4.2},
                {**potassium_event, "labevent_id": 2},
            ],
        }
        for table, values in source.items():
            load_table(conn, table, write_table(tmp_path, table, values))

    before = database.read_bytes()
    _, metadata = reference.snapshot_files(database)
    lock = tmp_path / "lock.json"
    lock.write_bytes(json_bytes(metadata, pretty=True))
    destination = tmp_path / "reference"
    assert reference.freeze_reference(database, destination, lock) == metadata
    assert reference.freeze_reference(database, destination, lock) == metadata
    assert database.read_bytes() == before
    row, = reference.read_reference(destination, lock)
    assert (row.labevent_id, row.value, row.unit) == (1, 4.2, "mmol/L")
    audit = json.loads((destination / "source_audit.jsonl").read_bytes())
    assert audit["source"]["labevent_id"] == 2
    assert audit["source"]["valueuom"] == "mEq/L"
    assert audit["disposition"] == "excluded_nonnumeric"
    with (destination / "observations.jsonl").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        reference.read_reference(destination, lock)
    with pytest.raises(ValueError, match="different contents"):
        reference.freeze_reference(database, destination, lock)


def test_snapshot_cannot_overwrite_different_run(tmp_path):
    destination = tmp_path / "run"
    file = "validator_input/observations.jsonl"
    publish_snapshot(destination, {file: b"first"})
    publish_snapshot(destination, {file: b"first"})
    with pytest.raises(ValueError, match="different contents"):
        publish_snapshot(destination, {file: b"second"})
    assert (destination / file).read_bytes() == b"first"
