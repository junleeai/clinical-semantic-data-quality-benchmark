"""Run the frozen Phase 5 protocol and publish identifier-free results."""

import argparse
import csv
import io
import json
import logging
import tempfile
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import numpy as np

from semantic_quality import analytical_impact as impact
from semantic_quality import cluster_bootstrap as bootstrap
from semantic_quality import detection, validation
from semantic_quality.corruption import RunSettings, generate_run
from semantic_quality.ingestion import RAW, ROOT, verify_checksum
from semantic_quality.reference import LOCK as REFERENCE_LOCK
from semantic_quality.reference import load_mappings, read_reference
from semantic_quality.snapshots import fingerprint, json_bytes, publish_snapshot
from semantic_quality.validation_models import mapping_key

CONFIG = ROOT / "configs/evaluation-v1.json"
OUTPUT = ROOT / "results/phase-5"
LOG = logging.getLogger(__name__)


def records(data):
    return tuple(json.loads(line) for line in data.splitlines())


def experiment_settings(protocol, *, clean):
    rates = (Decimal(0),) if clean else tuple(map(Decimal, protocol["nonzero_rates"]))
    seeds = (protocol["zero_seed"],) if clean else protocol["seeds"]
    for scenario in protocol["scenarios"]:
        for rate in rates:
            for seed in seeds:
                control = Decimal(protocol["a_control_rate"]) if scenario == "A" and rate else Decimal(0)
                yield RunSettings(scenario, seed, rate, control, protocol["batches"])


def validate_inputs(files, tiers, staging: Path):
    # Only the public input subtree crosses the validation boundary.
    for name, data in files.items():
        if name.startswith("validator_input/"):
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    findings = {}
    for tier in tiers:
        shared = validation.load_evidence(staging / "validator_input", tier)
        for method in validation.METHODS:
            findings[tier, method] = validation.validate(shared, method)
    return findings


def verify_foundation():
    reference_lock = json.loads(REFERENCE_LOCK.read_bytes())
    for name, digest in reference_lock["source_sha256"].items():
        verify_checksum(RAW / name, digest)
    validation_lock = validation.verify_validation_lock(3)
    frozen = read_reference()
    LOG.info("Verified raw file, reference, source audit, validator and registry hashes")
    return frozen, reference_lock, validation_lock


def benchmark_ids(settings, files, frozen_ids):
    integrated = records(files["validator_input/observations.jsonl"])
    inventory = records(files["validator_input/source_aware/upstream_inventory.jsonl"])
    inventory_ids = {row["labevent_id"] for row in inventory}
    integrated_ids = {row["labevent_id"] for row in integrated}
    if inventory_ids != frozen_ids or len(inventory_ids) != len(inventory):
        raise ValueError("The scenario upstream inventory differs from the frozen reference IDs")
    if integrated_ids - inventory_ids or len(integrated_ids) != len(integrated):
        raise ValueError("The integrated scenario contains unexpected or duplicate IDs")

    # Private labels are interpreted here, after both validators have run.
    obs_truth = records(files["ground_truth/observation_changes.jsonl"])
    map_truth = records(files["ground_truth/mapping_changes.jsonl"])
    injected = {row["labevent_id"] for row in obs_truth if row["is_error"]}
    omitted = inventory_ids - integrated_ids
    manifest_omitted = {row["labevent_id"] for row in obs_truth if row["is_error"] and row["corrupted"] is None}
    if omitted != manifest_omitted or (settings.scenario != "C" and omitted):
        raise ValueError("Manifest omissions and inventory reconciliation disagree")
    return integrated, inventory, integrated_ids, injected, obs_truth, map_truth


def evaluate_run(settings, files, findings, context, tables):
    integrated, inventory, integrated_ids, injected, obs_truth, map_truth = benchmark_ids(
        settings, files, context["ids"],
    )
    marker = {"scenario": settings.scenario, "target_rate": float(settings.rate), "seed": settings.seed}
    summary = json.loads(files["ground_truth/run.json"])
    mapping_keys = {mapping_key(row) for row in inventory}
    tables["runs"].append({
        **marker,
        "total_source_observations": len(inventory),
        "integrated_observations": len(integrated),
        "eligible_unit_observations": summary["eligible_unit_observations"],
        "eligible_mapping_entries": summary["eligible_mapping_entries"],
        "mapping_entries_before": len(mapping_keys),
        "mapping_entries_changed": len(map_truth),
        "affected_observations": len(injected),
        "realized_affected_observation_rate": detection.ratio(len(injected), len(inventory)),
        "realized_eligible_unit_rate": detection.ratio(len(injected), summary["eligible_unit_observations"]),
        "realized_mapping_rate": detection.ratio(len(map_truth), len(mapping_keys)),
        "realized_eligible_mapping_rate": detection.ratio(len(map_truth), summary["eligible_mapping_entries"]),
        "observations_absent": len(inventory) - len(integrated),
    })

    groups = {
        "observation": detection.positive_groups(context["ids"], obs_truth, "observation"),
        "mapping": detection.positive_groups(mapping_keys, map_truth, "mapping"),
    }
    baseline_stages = [
        ("reference", context["reference_numeric"], context["ids"], set(), set()),
        ("integrated", impact.numerical_rows(integrated, context["registry"]), integrated_ids, set(), injected),
    ]
    anchor = settings.rate and settings.seed == context["protocol"]["bootstrap_anchor_seed"]
    anchor_predictions = {}
    anchor_stages = {stage: values for stage, values, *_ in baseline_stages}
    for tier in context["protocol"]["tiers"]:
        for stage in baseline_stages:
            record_stage(tables, marker, tier, stage, context)
        for method in validation.METHODS:
            arm = findings[tier, method]
            observation, obs_unjoinable = detection.findings_by_severity(arm, "observation", context["ids"])
            mapping, map_unjoinable = detection.findings_by_severity(arm, "mapping", mapping_keys)
            unavailable = "Output-only cannot identify omitted observations" if tier == 1 and settings.scenario == "C" else ""
            map_unavailable = ("No mapping corruption in Scenario A" if settings.scenario == "A" else
                               "Feed mapping entries unavailable in Tier 1" if tier == 1 else "")
            for entity, flags, unknown, reason in (
                ("observation", observation, obs_unjoinable, unavailable),
                ("mapping", mapping, map_unjoinable, map_unavailable),
            ):
                tables["detection"].extend(
                    {**marker, "tier": tier, "method": method, "entity": entity, **row}
                    for row in detection.score_groups(groups[entity], flags, unknown, reason)
                )
            removed = impact.quarantine(integrated, observation["error"], mapping["error"])
            survivors = (row for row in integrated if row["labevent_id"] not in removed)
            stage = (method, impact.numerical_rows(survivors, context["registry"]), integrated_ids, removed, injected)
            record_stage(tables, marker, tier, stage, context)
            if settings.scenario == "C":
                record_omissions(tables, marker, tier, method, arm, integrated_ids, removed, context)
            if anchor and tier == 3:
                anchor_predictions[method] = observation["error"]
                anchor_stages[method] = stage[1]

    if anchor:
        record_bootstrap(tables, marker, context, inventory, injected, anchor_predictions, anchor_stages)
        if settings.rate == Decimal("0.05"):
            from semantic_quality.evaluation_reporting import cross_check
            tables["cross_checks"].extend(cross_check(
                marker, inventory, injected, anchor_predictions, obs_truth, map_truth,
                findings[3, "semantic"], integrated, context["registry"], baseline_stages[1][1],
            ))


def record_stage(tables, marker, tier, stage, context):
    name, by_analyte, integrated, removed, injected = stage
    numeric_ids = {event for rows in by_analyte.values() for event, _, _ in rows}
    for analyte, ids in context["source_ids"].items():
        unavailable = (ids & integrated) - removed - numeric_ids
        tables["impact"].append({
            **marker, "tier": tier, "stage": name,
            "source_unavailable_after_normalization": len(unavailable),
            **impact.summarize_stage(
                analyte, context["units"], by_analyte.get(analyte, ()), context["reference_stats"][analyte],
                ids, injected, integrated, removed,
            ),
        })


def record_omissions(tables, marker, tier, method, findings, integrated, removed, context):
    missing_findings = {
        finding.identifier["labevent_id"] for finding in findings
        if finding.rule_id == "source_observation_missing"
    }
    for analyte, ids in context["source_ids"].items():
        absent = ids - integrated
        tables["omissions"].append({
            **marker, "tier": tier, "method": method, "analyte": analyte,
            "upstream_observations": len(ids),
            "missing_at_integration": len(absent),
            "missing_identified_by_reconciliation": len(absent & missing_findings) if tier >= 2 else None,
            "integrated_then_quarantined": len(ids & removed),
            "physically_available": len((ids & integrated) - removed),
        })


def record_bootstrap(tables, marker, context, inventory, injected, predictions, stages):
    protocol = context["protocol"]
    replicates = protocol["bootstrap_replicates"]
    index, weights = bootstrap.patient_weights(inventory, replicates, protocol["bootstrap_seed"])
    tables["detection_intervals"].extend(
        {**marker, "tier": 3, "contrast": "semantic_minus_conventional", "replicates": replicates, **row}
        for row in bootstrap.detection_bootstrap(inventory, injected, predictions, index, weights)
    )
    for analyte in context["source_ids"]:
        points = {stage: impact.summarize(data.get(analyte, ())) for stage, data in stages.items()}
        draws = {
            stage: bootstrap.weighted_statistics(data.get(analyte, ()), index, weights)
            for stage, data in stages.items()
        }
        reference_point, reference_draws = points["reference"], draws["reference"]
        for stage in ("integrated", *validation.METHODS):
            for metric in ("mean", "median", "patient_weighted_mean", "patients"):
                value, reference = points[stage][metric], reference_point[metric]
                point = value - reference if value is not None and reference is not None else None
                tables["impact_intervals"].append({
                    **marker, "tier": 3, "analyte": analyte, "contrast": f"{stage}_minus_reference",
                    "metric": metric, "replicates": replicates,
                    **bootstrap.conditional_interval(point, draws[stage][metric] - reference_draws[metric]),
                })
        semantic, baseline, clean = (points[stage]["mean"] for stage in ("semantic", "conventional", "reference"))
        point = abs(semantic - clean) - abs(baseline - clean) if None not in (semantic, baseline, clean) else None
        values = np.abs(draws["semantic"]["mean"] - reference_draws["mean"]) - np.abs(
            draws["conventional"]["mean"] - reference_draws["mean"]
        )
        tables["impact_intervals"].append({
            **marker, "tier": 3, "analyte": analyte, "contrast": "semantic_minus_conventional",
            "metric": "absolute_mean_distortion", "replicates": replicates,
            **bootstrap.conditional_interval(point, values),
        })


def csv_bytes(rows):
    if not rows:
        raise ValueError("An expected result table is empty")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def run_benchmark(output=OUTPUT):
    from semantic_quality.evaluation_reporting import aggregate_and_plot

    protocol = json.loads(CONFIG.read_bytes())
    frozen, reference_lock, validation_lock = verify_foundation()
    mappings = load_mappings()
    registry = json.loads((ROOT / validation.REGISTRY).read_bytes())
    source_ids = {analyte: set() for analyte in registry["profiles"]}
    for row in frozen:
        source_ids[registry["sources"][str(row.itemid)]["analyte"]].add(row.labevent_id)
    reference_numeric = impact.numerical_rows(map(asdict, frozen), registry)
    context = {
        "protocol": protocol, "registry": registry, "source_ids": source_ids,
        "units": {key: profile["unit"] for key, profile in registry["profiles"].items()},
        "ids": {row.labevent_id for row in frozen},
        "reference_numeric": reference_numeric,
        "reference_stats": {key: impact.summarize(rows) for key, rows in reference_numeric.items()},
    }
    tables = {name: [] for name in (
        "runs", "detection", "impact", "omissions", "detection_intervals", "impact_intervals", "cross_checks",
    )}
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary).resolve()
        clean_runs = []
        clean_inputs = None
        for settings in experiment_settings(protocol, clean=True):
            files, _ = generate_run(frozen, mappings, settings)
            clean = {name: data for name, data in files.items() if name.startswith("validator_input/")}
            if clean_inputs is not None and clean != clean_inputs:
                raise ValueError("Zero-rate scenarios disagree on validator inputs")
            clean_inputs = clean
            findings = validate_inputs(clean, protocol["tiers"], staging)
            if any(findings.values()):
                raise ValueError("Unexpected findings on a zero-rate control; frozen rules require review")
            clean_runs.append((settings, files, findings))
        LOG.info("All three clean controls have identical validator inputs and no findings")
        for settings, files, findings in clean_runs:
            evaluate_run(settings, files, findings, context, tables)

        for run_number, settings in enumerate(experiment_settings(protocol, clean=False), 1):
            files, _ = generate_run(frozen, mappings, settings)
            findings = validate_inputs(files, protocol["tiers"], staging)
            evaluate_run(settings, files, findings, context, tables)
            if run_number % len(protocol["seeds"]) == 0:
                LOG.info("Completed %s perturbed runs (through %s at %s)", run_number, settings.scenario, settings.rate)

    aggregates = {f"{name}.csv": csv_bytes(rows) for name, rows in tables.items()}
    aggregates.update(aggregate_and_plot(aggregates))
    provenance = {
        "protocol_version": protocol["version"],
        "protocol_config_sha256": fingerprint(CONFIG.read_bytes()),
        "validation_lock_version": validation_lock["version"],
        "validation_lock_sha256": fingerprint(validation.LOCK.read_bytes()),
        "registry_version": registry["version"],
        "reference_observations_sha256": reference_lock["observations_sha256"],
        "source_checksums_verified": True,
        "unexpected_clean_findings": 0,
        "runs": len(tables["runs"]),
        "validator_method_tier_runs": len(tables["runs"]) * len(protocol["tiers"]) * len(validation.METHODS),
        "bootstrap_replicates_per_anchor": protocol["bootstrap_replicates"],
    }
    aggregates["provenance.json"] = json_bytes(provenance, pretty=True)
    publish_snapshot(output.resolve(), aggregates)
    LOG.info("Wrote aggregate results to %s", output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT, help="Directory for aggregate result files.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        run_benchmark(args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Evaluation stopped: {error}\n")


if __name__ == "__main__":
    main()
