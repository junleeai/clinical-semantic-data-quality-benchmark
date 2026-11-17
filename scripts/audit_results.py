"""Independently audit published counts and reconstruct the creatinine failure."""

import csv
import json
import math
import tempfile
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import median

import duckdb

from semantic_quality.corruption import RunSettings, generate_run
from semantic_quality.reference import load_mappings, read_reference
from semantic_quality.validation import load_evidence, validate

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "phase-5"
OUTPUTS = ROOT / "results" / "audit"


def load_csv(name):
    with (RESULTS / name).open(newline="") as source:
        return list(csv.DictReader(source))


def write_csv(name, rows):
    with (OUTPUTS / name).open("w", newline="") as target:
        writer = csv.DictWriter(target, list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def audit_detection():
    totals = defaultdict(lambda: [0, 0, 0, 0, 0])
    for row in load_csv("detection.csv"):
        if row["subtype"] != "all" or float(row["target_rate"]) == 0:
            continue
        keys = [row[k] for k in ("scenario", "tier", "method", "entity", "policy")]
        for group in (tuple(keys), ("all", *keys[1:])) if row["available"] == "True" else ():
            for i, field in enumerate(("tp", "fp", "tn", "fn", "review_only_count")):
                totals[group][i] += int(row[field])

    result = []
    for (scenario, tier, method, entity, policy), (tp, fp, tn, fn, review) in sorted(totals.items()):
        result.append({
            "scenario": scenario, "tier": tier, "method": method, "entity": entity, "policy": policy,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "review_only": review,
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        })
    primary = {
        (row["scenario"], row["tier"], row["method"]): row["recall"]
        for row in result if row["entity"] == "observation" and row["policy"] == "error_only"
    }
    baseline = primary["all", "3", "conventional"]
    semantic = primary["all", "3", "semantic"]
    assert (round(100 * baseline, 2), round(100 * semantic, 2), round(100 * (semantic - baseline), 2)) == (
        35.24, 74.60, 39.36,
    )
    assert [round(100 * primary[key], 2) for key in (
        ("A", "3", "semantic"), ("B", "3", "semantic"), ("C", "2", "conventional"),
    )] == [25.18, 78.14, 100]
    by_unit = {
        (row["scenario"], row["tier"], row["method"], row["entity"], row["policy"]): row
        for row in result
    }
    for method in ("conventional", "semantic"):
        for tier in ("2", "3"):
            for entity, expected in (("observation", 21306), ("mapping", 150)):
                omission = by_unit["C", tier, method, entity, "error_only"]
                assert (omission["tp"], omission["fn"]) == (expected, 0)
        assert ("C", "1", method, "observation", "error_only") not in by_unit
    for entity, error_count, review_count in (("mapping", 143, 37), ("observation", 20563, 5753)):
        certain = by_unit["B", "3", "semantic", entity, "error_only"]
        inclusive = by_unit["B", "3", "semantic", entity, "include_review"]
        assert (certain["tp"], certain["fn"], certain["review_only"]) == (error_count, review_count, review_count)
        assert (inclusive["tp"], inclusive["fn"]) == (error_count + review_count, 0)
    assert all(row["fp"] == 0 for row in result)
    return result


def scenario_inputs(settings, reference, mappings, staging):
    files, _ = generate_run(reference, mappings, settings)
    for name, contents in files.items():
        if name.startswith("validator_input/"):
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
    findings = validate(load_evidence(staging / "validator_input", 3), "semantic")
    removed = {
        finding.identifier["labevent_id"] for finding in findings
        if finding.severity == "error" and finding.entity == "observation"
    }
    assert not any(finding.severity == "error" and finding.entity == "mapping" for finding in findings)
    return files, removed


def audit_creatinine():
    """Use independent DuckDB joins and explicit CDC factors, separate from the evaluator."""
    frozen = read_reference()
    mappings = load_mappings()
    published = {
        (int(row["seed"]), row["stage"]): row
        for row in load_csv("impact.csv")
        if row["scenario"] == "A" and row["analyte"] == "creatinine"
        and row["tier"] == "3" and float(row["target_rate"]) == .05
    }
    protocol = json.loads((ROOT / "configs/evaluation-v1.json").read_bytes())
    observations, subtypes = [], []

    with tempfile.TemporaryDirectory() as directory, duckdb.connect() as connection:
        staging = Path(directory).resolve()
        connection.execute("CREATE TABLE source (id BIGINT, clean DOUBLE)")
        connection.executemany("INSERT INTO source VALUES (?, ?)", [
            (row.labevent_id, row.value) for row in frozen if row.itemid == 50912
        ])
        connection.execute("""
            CREATE TABLE reported (id BIGINT, amount DOUBLE, unit VARCHAR, removed BOOLEAN);
            CREATE TABLE labels (id BIGINT, subtype VARCHAR);
            CREATE VIEW creatinine AS
            SELECT clean, removed, coalesce(subtype, 'unchanged') AS subtype,
                CASE unit WHEN 'mg/dL' THEN amount WHEN 'umol/L' THEN amount / 88.4 END AS canonical
            FROM source JOIN reported USING (id)
            LEFT JOIN labels USING (id);
        """)
        for seed in protocol["seeds"]:
            run = RunSettings("A", seed, Decimal(".05"), Decimal(".05"), protocol["batches"])
            files, removed = scenario_inputs(run, frozen, mappings, staging)
            connection.execute("DELETE FROM reported; DELETE FROM labels;")
            integrated = [json.loads(line) for line in files["validator_input/observations.jsonl"].splitlines()]
            connection.executemany("INSERT INTO reported VALUES (?, ?, ?, ?)", [
                (row["labevent_id"], row["value"], row["unit"], row["labevent_id"] in removed)
                for row in integrated if row["itemid"] == 50912
            ])
            # Only the audit reads the true subtype labels.
            labels = [json.loads(line) for line in files["ground_truth/observation_changes.jsonl"].splitlines()]
            connection.executemany("INSERT INTO labels VALUES (?, ?)", [
                (row["labevent_id"], row["subtype"]) for row in labels if row["itemid"] == 50912
            ])
            n, n_valid, n_removed, clean, before, after, removed_mean, clean_median, before_median, after_median = (
                connection.execute("""
                    SELECT count(*), count(canonical), count(*) FILTER (WHERE removed),
                        avg(clean), avg(canonical), avg(canonical) FILTER (WHERE NOT removed),
                        avg(canonical) FILTER (WHERE removed),
                        median(clean), median(canonical), median(canonical) FILTER (WHERE NOT removed)
                    FROM creatinine
                """).fetchone()
            )
            assert n == n_valid == 3003
            assert math.isclose(after - before, n_removed * (before - removed_mean) / (n - n_removed), abs_tol=1e-12)
            for stage, mean in (("reference", clean), ("integrated", before), ("semantic", after)):
                assert math.isclose(mean, float(published[seed, stage]["mean"]), abs_tol=1e-12)
            top10_share = connection.execute("""
                WITH positive AS (
                    SELECT canonical - clean AS delta FROM creatinine WHERE canonical > clean
                ), ranked AS (
                    SELECT delta, row_number() OVER (ORDER BY delta DESC) AS rank FROM positive
                )
                SELECT sum(delta) FILTER (WHERE rank <= 10) / sum(delta) FROM ranked
            """).fetchone()[0]
            observations.append({
                "seed": seed, "target_rate": .05, "source_observations": n, "quarantined": n_removed,
                "reference_mean_mg_dl": clean, "integrated_mean_mg_dl": before, "semantic_mean_mg_dl": after,
                "removed_mean_mg_dl": removed_mean, "reference_median_mg_dl": clean_median,
                "integrated_median_mg_dl": before_median, "semantic_median_mg_dl": after_median,
                "integrated_relative_mean_distortion": abs(before - clean) / abs(clean),
                "semantic_relative_mean_distortion": abs(after - clean) / abs(clean),
                "top_10_share_of_positive_value_increase": top10_share,
            })
            for subtype, count, quarantined, change, remaining in connection.execute("""
                SELECT subtype, count(*), count(*) FILTER (WHERE removed),
                    sum(canonical - clean), coalesce(sum(canonical - clean) FILTER (WHERE NOT removed), 0)
                FROM creatinine GROUP BY subtype ORDER BY subtype
            """).fetchall():
                subtypes.append({
                    "seed": seed, "subtype": subtype, "observations": count, "quarantined": quarantined,
                    "integrated_sum_of_value_changes_mg_dl": change,
                    "retained_sum_of_value_changes_mg_dl": remaining,
                })
    assert round(100 * median(row["integrated_relative_mean_distortion"] for row in observations), 2) == 216.07
    assert round(100 * median(row["semantic_relative_mean_distortion"] for row in observations), 2) == 220.11
    return observations, subtypes


def main():
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    detection = audit_detection()
    overview, subtypes = audit_creatinine()
    write_csv("pooled_detection.csv", detection)
    write_csv("creatinine_runs.csv", overview)
    write_csv("creatinine_subtypes.csv", subtypes)
    print("Independent count arithmetic and 10-seed creatinine reconstruction passed.")


if __name__ == "__main__":
    main()
