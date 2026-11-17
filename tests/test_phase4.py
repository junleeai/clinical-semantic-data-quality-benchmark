"""Exercise both validation methods with fabricated, scenario-independent inputs."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from semantic_quality import validation
from semantic_quality.snapshots import jsonl_bytes
from semantic_quality.validation_models import IDENTITY, Evidence


def observation(**changes):
    return {
        "labevent_id": 1, "subject_id": 2, "specimen_id": 3, "itemid": 50931,
        "batch_id": "demo", "charttime": "2100-02-01T00:00:00", "loinc": "2345-7",
        "value": 90.0, "unit": "mg/dL", "lower_bound": 70.0, "upper_bound": 100.0,
        **changes,
    }


def inventory_row(row):
    return {field: row[field] for field in IDENTITY}


def feed_row(row):
    return {field: row[field] for field in ("batch_id", "itemid", "loinc")}


@pytest.fixture
def registry():
    return json.loads((validation.ROOT / validation.REGISTRY).read_bytes())


def load_test_input(tmp_path, outputs):
    root = tmp_path / "validator_input"
    source = root / "source_aware"
    source.mkdir(parents=True)
    (root / "observations.jsonl").write_bytes(jsonl_bytes(outputs))
    (source / "upstream_inventory.jsonl").write_bytes(jsonl_bytes(map(inventory_row, outputs)))
    (source / "feed_mappings.jsonl").write_bytes(jsonl_bytes(map(feed_row, outputs)))
    return root


def assert_same_findings(evidence):
    baseline, semantic = (validation.validate(evidence, method) for method in validation.METHODS)
    without_method = lambda rows: [{k: v for k, v in asdict(row).items() if k != "method"} for row in rows]
    assert without_method(baseline) == without_method(semantic)
    return baseline


@pytest.mark.parametrize("tier", [1, 2, 3])
def test_clean_observations_pass_at_every_tier(tmp_path, tier):
    root = load_test_input(tmp_path, [
        observation(),
        observation(labevent_id=2, itemid=50971, loinc="2823-3", value=4.1, unit="mmol/L",
                    lower_bound=3.4, upper_bound=5.0),
    ])
    evidence = validation.load_evidence(root, tier)
    assert validation.validate_pair(evidence) == ()


def test_schema_types_duplicates_and_generic_limits():
    invalid = observation(labevent_id=True, value=float("nan"), unit="", charttime="invalid", loinc="word")
    del invalid["itemid"]
    other = observation(value=-4, lower_bound=100, upper_bound=70)
    findings = assert_same_findings(Evidence(1, (invalid, other, observation())))
    assert {row.rule_id for row in findings} == {
        "observation_schema", "required_value_missing", "observation_field_type",
        "generic_concentration_review", "reference_bounds_reversed", "duplicate_observation_id",
    }
    fields = next(row for row in findings if row.rule_id == "observation_field_type")
    assert fields.identifier == {"input_line": 1}
    assert fields.evidence["fields"] == ["charttime", "labevent_id", "loinc", "value"]


def test_reconciliation_detects_missing_and_unexpected_outputs_for_both_methods():
    missing = observation(labevent_id=10, itemid=50971, loinc="2823-3")
    present = observation()
    extra = observation(labevent_id=90)
    output = (observation(specimen_id=400), extra)
    assert validation.validate_pair(Evidence(1, output)) == ()
    tier2 = Evidence(2, output, (inventory_row(missing), inventory_row(present)), (feed_row(present),))
    findings = assert_same_findings(tier2)
    by_rule = {row.rule_id: row.identifier for row in findings}
    assert by_rule == {
        "source_observation_missing": {"labevent_id": 10},
        "unexpected_output_observation": {"labevent_id": 90},
        "source_identity_mismatch": {"labevent_id": 1},
        "required_feed_mapping_missing": {"batch_id": "demo", "itemid": 50971},
    }
    assert tier2.inventory[0] == inventory_row(missing)


def test_mapping_integrity_is_shared():
    present = observation()
    invalid_feed = feed_row(observation(loinc=None))
    unused_feed = feed_row(observation(batch_id="other"))
    evidence = Evidence(2, (present,), (inventory_row(present),), (invalid_feed, invalid_feed, unused_feed))
    assert {finding.rule_id for finding in assert_same_findings(evidence)} == {
        "invalid_feed_target", "required_feed_mapping_missing", "duplicate_feed_mapping",
        "unused_feed_mapping", "output_without_feed_mapping",
    }


@pytest.mark.parametrize("changes", [
    {"value": 4.9959, "unit": "mmol/L", "loinc": "14749-6", "lower_bound": 3.8857, "upper_bound": 5.551},
    {"value": 79.56, "unit": "umol/L", "loinc": "14682-9", "itemid": 50912,
     "lower_bound": 44.2, "upper_bound": 106.08},
    {"value": 4.1, "unit": "mEq/L", "loinc": "2823-3", "itemid": 50971},
    {"value": 141, "unit": "mEq/L", "loinc": "2951-2", "itemid": 50983},
    # A reported molar glucose value can be internally coherent even when its original is unknown.
    {"value": 5.49549, "unit": "mmol/L", "loinc": "14749-6", "lower_bound": 3.8857, "upper_bound": 5.551},
])
def test_valid_alternate_units_and_plausible_values_are_accepted(registry, changes):
    row = observation(**changes)
    evidence = Evidence(3, (row,), (inventory_row(row),), (feed_row(observation(itemid=row["itemid"],
                        loinc=registry["sources"][str(row["itemid"])]["preferred_loinc"])),), registry)
    assert validation.validate_pair(evidence) == ()


@pytest.mark.parametrize("changes,rule,severity", [
    ({"unit": "mmol/L"}, "concept_unit_conflict", "error"),
    ({"unit": "mEq/L", "loinc": "14749-6"}, "concept_unit_conflict", "error"),
    ({"unit": "arbitrary"}, "unit_outside_registry", "review"),
    ({"itemid": 50912, "loinc": "14682-9", "unit": "umol/L", "value": 15000},
     "normalized_concentration_review", "review"),
    ({"itemid": 50971, "loinc": "2951-2", "unit": "mmol/L", "value": 4},
     "analyte_concept_mismatch", "error"),
    ({"loinc": "2350-7"}, "specimen_class_conflict", "error"),
    ({"itemid": 50983, "loinc": "2947-0", "unit": "mmol/L", "value": 140},
     "specimen_mapping_uncertain", "review"),
])
def test_semantic_interpretation_uses_registered_meaning(registry, changes, rule, severity):
    row = observation(**changes)
    inventory, feed = (inventory_row(row),), (feed_row(row),)
    assert validation.validate_pair(Evidence(2, (row,), inventory, feed)) == ()
    evidence = Evidence(3, (row,), inventory, feed, registry)
    assert validation.validate(evidence, "conventional") == ()
    findings = validation.validate(evidence, "semantic")
    assert {finding.rule_id for finding in findings} == {rule}
    assert {finding.severity for finding in findings} == {severity}
    if rule in {"analyte_concept_mismatch", "specimen_class_conflict", "specimen_mapping_uncertain"}:
        assert {finding.entity for finding in findings} == {"mapping", "observation"}


def test_catalog_coverage_is_shared_and_unknown_codes_are_only_reviewed(registry):
    row = observation(loinc="1234-5")
    evidence = Evidence(3, (row,), (inventory_row(row),), (feed_row(row),), registry)
    findings = assert_same_findings(evidence)
    assert {finding.rule_id for finding in findings} == {"target_code_outside_registry"}
    assert {finding.severity for finding in findings} == {"review"}


def test_loader_reads_only_tier_files_and_both_methods_receive_same_object(tmp_path, monkeypatch):
    root = load_test_input(tmp_path, [observation()])
    private = root.parent / "ground_truth"
    private.mkdir()
    (private / "observation_changes.jsonl").write_text("This file must not be read.")
    observed = []
    original_open = Path.open

    def audited_open(self, *args, **kwargs):
        path = self.resolve()
        assert private not in path.parents
        assert path.name not in {"lab-mappings.csv", "reference-lock.json", "corruption.py"}
        observed.append(path)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", audited_open)
    for tier in (1, 2, 3):
        observed.clear()
        evidence = validation.load_evidence(root, tier)
        inside = {str(path.relative_to(root)) for path in observed if path.is_relative_to(root)}
        expected = {"observations.jsonl"}
        if tier >= 2:
            expected |= {"source_aware/upstream_inventory.jsonl", "source_aware/feed_mappings.jsonl"}
        assert inside == expected
        assert ((validation.ROOT / validation.REGISTRY) in observed) == (tier == 3)
        assert (evidence.registry is not None) == (tier == 3)

    calls = []

    def capture(shared, method):
        calls.append((shared, method))
        return ()

    monkeypatch.setattr(validation, "validate", capture)
    validation.validate_pair(evidence)
    assert [method for _, method in calls] == ["conventional", "semantic"]
    assert all(shared is evidence for shared, _ in calls)


def test_loader_refuses_symlink_escape_before_reading_private_file(tmp_path):
    root = load_test_input(tmp_path, [observation()])
    target = root.parent / "private.jsonl"
    target.write_text("File contents must never be parsed.")
    inventory = root / "source_aware" / "upstream_inventory.jsonl"
    inventory.unlink()
    inventory.symlink_to(target)
    assert validation.load_evidence(root, 1).inventory == ()
    with pytest.raises(ValueError, match="leaves the declared input tree"):
        validation.load_evidence(root, 2)


def test_finding_output_is_deterministic_and_does_not_echo_extraneous_columns():
    rows = (observation(labevent_id=20, value=-8, secret_label=True), observation(labevent_id=7, unit=None))
    files = [jsonl_bytes(asdict(row) for row in validation.validate_pair(Evidence(1, order)))
             for order in (rows, rows, tuple(reversed(rows)))]
    assert files[0] == files[1] == files[2]
    assert b"secret_label" not in files[0]


def test_tier_three_fails_closed_if_registry_changes(tmp_path, monkeypatch):
    root = load_test_input(tmp_path, [observation()])
    registry_file = tmp_path / validation.REGISTRY
    registry_file.parent.mkdir()
    registry_file.write_text("{}")
    lock_file = tmp_path / "validation-lock.json"
    lock_file.write_text(json.dumps({
        "files_sha256": {validation.REGISTRY: "unchanged SHA-256"},
    }))
    monkeypatch.setattr(validation, "ROOT", tmp_path)
    monkeypatch.setattr(validation, "LOCK", lock_file)
    assert validation.load_evidence(root, 1).registry is None
    with pytest.raises(ValueError, match="Frozen validation file changed"):
        validation.load_evidence(root, 3)
