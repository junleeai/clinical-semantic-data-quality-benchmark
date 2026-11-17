"""Check scoring, quarantine and cluster resampling with fabricated inputs."""

import json
from pathlib import Path

import numpy as np
import pytest

from semantic_quality import analytical_impact as impact
from semantic_quality import cluster_bootstrap as bootstrap
from semantic_quality import detection, evaluation, validation
from semantic_quality.snapshots import jsonl_bytes
from semantic_quality.validation_models import Finding


def finding(entity, identifier, severity="error"):
    return Finding(entity, identifier, "example_rule", "conventional", 3, severity, "Example", {}, "review")


def test_confusion_and_metrics():
    counts = detection.confusion({1, 2, 3, 4, 5}, {1, 2}, {1, 3, 5, 99})
    assert counts == {"tp": 1, "fp": 2, "tn": 1, "fn": 1}
    assert detection.metrics_from_counts(**counts) == {
        "precision": 1 / 3, "recall": .5, "f1": .4, "false_positive_rate": 2 / 3,
    }


def test_undefined_metrics_are_distinct_from_zero_scores():
    assert detection.metrics_from_counts(0, 0, 0, 0) == dict.fromkeys(detection.METRICS)
    assert detection.metrics_from_counts(0, 0, 8, 2) == {
        "precision": None, "recall": 0, "f1": 0, "false_positive_rate": 0,
    }


def test_duplicate_findings_and_review_workload():
    entity = "observation"
    signals = [
        finding(entity, {"labevent_id": 1}), finding(entity, {"labevent_id": 1}),
        finding(entity, {"labevent_id": 1}, "review"), finding(entity, {"labevent_id": 2}, "review"),
        finding(entity, {"input_line": 4}),
        finding("mapping", {"batch_id": "a", "itemid": 10}),
    ]
    flags, unknown = detection.findings_by_severity(signals, entity, {1, 2, 3})
    primary, secondary = list(detection.score_groups([("all", {1, 2, 3}, {1})], flags, unknown, ""))
    assert (primary["tp"], primary["fp"], primary["reviewed_count"], primary["review_only_count"]) == (1, 0, 2, 1)
    assert (secondary["tp"], secondary["fp"], secondary["unjoinable_identifiers_run"]) == (1, 1, 1)


def test_subtype_negatives_exclude_different_injected_error_types():
    changes = [
        {"scenario": "B", "labevent_id": 1, "subtype": "swap", "is_error": True, "corrupted": {}},
        {"scenario": "B", "labevent_id": 2, "subtype": "specimen", "is_error": True, "corrupted": {}},
        {"scenario": "B", "labevent_id": 4, "subtype": "control", "is_error": False},
    ]
    groups = {name: (universe, positives) for name, universe, positives in detection.positive_groups(
        {1, 2, 3, 4}, changes, "observation",
    )}
    assert groups["swap"] == ({1, 3, 4}, {1})
    assert groups["control"] == ({4}, set())


def test_mapping_and_omission_scoring_have_separate_units():
    mappings = {("a", 10), ("b", 10)}
    signals = [
        finding("mapping", {"batch_id": "a", "itemid": 10}),
        finding("observation", {"labevent_id": 1}), finding("observation", {"labevent_id": 2}),
    ]
    flags, _ = detection.findings_by_severity(signals, "mapping", mappings)
    assert detection.confusion(mappings, {("a", 10)}, flags["error"]) == {
        "tp": 1, "fp": 0, "tn": 1, "fn": 0,
    }
    obs_flags, _ = detection.findings_by_severity(signals, "observation", {1, 2, 3})
    tier2 = next(detection.score_groups([("all", {1, 2, 3}, {1, 2})], obs_flags, 0, ""))
    tier1 = next(detection.score_groups([("all", {1, 2, 3}, {1, 2})], obs_flags, 0, "unavailable"))
    assert tier2["tp"] == 2 and tier2["fn"] == 0
    assert not tier1["available"] and all(tier1[name] is None for name in detection.COUNT_KEYS)


def test_quarantine_removes_only_present_rows_and_preserves_inputs():
    rows = [{"labevent_id": 1, "batch_id": "a", "itemid": 10},
            {"labevent_id": 2, "batch_id": "a", "itemid": 20},
            {"labevent_id": 3, "batch_id": "b", "itemid": 20}]
    before = jsonl_bytes(rows)
    assert impact.quarantine(rows, {1, 99}, {("a", 20), ("c", 20)}) == {1, 2}
    assert jsonl_bytes(rows) == before


@pytest.fixture
def registry():
    return json.loads((validation.ROOT / validation.REGISTRY).read_bytes())


@pytest.mark.parametrize("code,unit,value,analyte,expected", [
    ("14749-6", "mmol/L", 4.9959, "glucose", 90),
    ("2345-7", "mmol/L", 4.9959, "glucose", 90),  # Consumer trusts reported unit.
    ("14682-9", "umol/L", 88.4, "creatinine", 1),
    ("2823-3", "mEq/L", 4, "potassium", 4),
    ("2951-2", "mmol/L", 140, "sodium", 140),
])
def test_analytics_use_coded_analyte_and_reported_unit(registry, code, unit, value, analyte, expected):
    row = {"itemid": 999, "loinc": code, "unit": unit, "value": value}
    name, amount = impact.canonical_value(row, registry)
    assert name == analyte and amount == pytest.approx(expected)


def test_retention_distinguishes_omission_and_numeric_coded_counts():
    source = {1, 2, 3}
    ref = impact.summarize([(1, 10, 8), (2, 10, 10), (3, 11, 12)])
    row = impact.summarize_stage(
        "test", {"test": "mg/dL"}, [(2, 10, 10), (4, 11, 40)], ref,
        source, {3}, {1, 2, 4}, {1},
    )
    assert row["source_absent_at_integration"] == 1 and row["source_quarantined"] == 1
    assert row["corrupted_retained"] == 0
    assert row["corrupted_retained_among_present_rate"] is None
    assert row["clean_quarantined_rate"] == .5
    assert row["source_analyte_retention"] == 1 / 3
    assert row["observations"] == 2 and row["mean_absolute_distortion"] == 15


def test_patient_weights_preserve_batch_sizes_and_are_deterministic():
    rows = tuple({"subject_id": patient, "batch_id": batch}
                 for patient, batch in [(1, "a"), (1, "a"), (2, "a"), (3, "b"), (4, "b")])
    index, weights = bootstrap.patient_weights(rows, 13, 11)
    assert index == {1: 0, 2: 1, 3: 2, 4: 3}
    np.testing.assert_array_equal(weights[:, :2].sum(axis=1), [2] * 13)
    np.testing.assert_array_equal(weights[:, 2:].sum(axis=1), [2] * 13)
    np.testing.assert_array_equal(weights, bootstrap.patient_weights(tuple(reversed(rows)), 13, 11)[1])
    assert not np.array_equal(weights, bootstrap.patient_weights(rows, 13, 7)[1])


def test_patient_bootstrap_weighted_summaries_equal_expanded_rows():
    rows = [(1, 1, 2), (2, 1, 10), (3, 2, 30)]
    weights = np.array([[1, 1], [2, 0], [0, 2]])
    draws = bootstrap.weighted_statistics(rows, {1: 0, 2: 1}, weights)
    for replicate, counts in enumerate(weights):
        expanded = [(key, (patient, copy), value)
                    for key, patient, value in rows for copy in range(counts[patient - 1])]
        expected = impact.summarize(expanded)
        for metric in draws:
            assert draws[metric][replicate] == expected[metric]


def test_a_single_paired_weight_vector_yields_no_artificial_precision():
    inventory = [{"labevent_id": 1, "subject_id": 1}, {"labevent_id": 2, "subject_id": 2}]
    rows = bootstrap.detection_bootstrap(
        inventory, {1}, {"conventional": set(), "semantic": {1}}, {1: 0, 2: 1},
        np.array([[1, 1], [2, 0], [0, 2]]),
    )
    precision, recall = rows[:2]
    assert precision["estimate"] is None and precision["valid_replicates"] == 0
    assert (recall["estimate"], recall["lower_95"], recall["upper_95"], recall["valid_replicates"]) == (1, 1, 1, 2)


def test_validator_staging_excludes_private_bytes_and_shares_evidence(tmp_path, monkeypatch):
    provided = {
        "validator_input/observations.jsonl": b"{}\n",
        "ground_truth/run.json": b"private seed",
        "ground_truth/observation_changes.jsonl": b"private manifest",
    }
    loaded = []
    validated = []

    def load(path: Path, tier):
        assert path.parent == tmp_path
        assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == ["observations.jsonl"]
        result = object()
        loaded.append((tier, result))
        return result

    def validate(evidence, name):
        validated.append((evidence, name))
        return ()

    monkeypatch.setattr(validation, "load_evidence", load)
    monkeypatch.setattr(validation, "validate", validate)
    assert len(evaluation.validate_inputs(provided, [1, 2, 3], tmp_path)) == 6
    for index, (_, evidence) in enumerate(loaded):
        assert validated[index * 2:index * 2 + 2] == [(evidence, "conventional"), (evidence, "semantic")]


def test_benchmark_omitted_ids_match_manifest_and_reference_is_read_only():
    source = [{"labevent_id": 1}, {"labevent_id": 2}]
    files = {
        "validator_input/observations.jsonl": jsonl_bytes(source[:1]),
        "validator_input/source_aware/upstream_inventory.jsonl": jsonl_bytes(source),
        "ground_truth/observation_changes.jsonl": jsonl_bytes(
            [{"labevent_id": 2, "is_error": True, "corrupted": None}]
        ),
        "ground_truth/mapping_changes.jsonl": b"",
    }
    protocol = json.loads(evaluation.CONFIG.read_text())
    settings = next(settings for settings in evaluation.experiment_settings(protocol, clean=False)
                    if settings.scenario == "C")
    before = dict(files)
    assert evaluation.benchmark_ids(settings, files, {1, 2})[2:4] == ({1}, {2})
    assert files == before
    files["ground_truth/observation_changes.jsonl"] = b""
    with pytest.raises(ValueError, match="Manifest omissions"):
        evaluation.benchmark_ids(settings, files, {1, 2})
