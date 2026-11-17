"""Summarize aggregate result tables with SQL and render reproducible figures."""

import csv
import io
import math
import tempfile
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from semantic_quality import analytical_impact as impact, detection
from semantic_quality.ingestion import ROOT
from semantic_quality.validation_models import mapping_key

COLORS = {"conventional": "#355C8C", "semantic": "#B54B31", "integrated": "#817663"}
ANALYTES = ("creatinine", "glucose", "potassium", "sodium")
SCENARIOS = {"A": "Unit and value errors", "B": "Incorrect mappings", "C": "Incomplete mappings"}


def cross_check(marker, inventory, injected, predictions, obs_truth, map_truth, semantic_findings,
                integrated, registry, numeric_rows):
    """Cross-check raw counts and canonical statistics with independent SQL operations."""
    checks = []

    def compare(metric, python_value, sql_value):
        if not math.isclose(python_value, sql_value, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"Independent SQL check failed for {metric}")
        checks.append({**marker, "check": metric, "python": python_value, "duckdb": sql_value})

    with duckdb.connect() as connection:
        connection.execute("""
            CREATE TABLE observations (id BIGINT PRIMARY KEY);
            CREATE TABLE observed_truth (id BIGINT PRIMARY KEY);
            CREATE TABLE predictions (id BIGINT PRIMARY KEY);
        """)
        connection.executemany("INSERT INTO observations VALUES (?)", [(row["labevent_id"],) for row in inventory])
        connection.executemany("INSERT INTO observed_truth VALUES (?)", [
            (row["labevent_id"],) for row in obs_truth if row["is_error"]
        ])
        for method, ids in predictions.items():
            connection.execute("DELETE FROM predictions")
            if ids:
                connection.executemany("INSERT INTO predictions VALUES (?)", [(key,) for key in sorted(ids)])
            actual_counts = connection.execute("""
                SELECT
                    count(*) FILTER (WHERE t.id IS NOT NULL AND p.id IS NOT NULL),
                    count(*) FILTER (WHERE t.id IS NULL AND p.id IS NOT NULL),
                    count(*) FILTER (WHERE t.id IS NULL AND p.id IS NULL),
                    count(*) FILTER (WHERE t.id IS NOT NULL AND p.id IS NULL)
                FROM observations o
                LEFT JOIN observed_truth t ON o.id = t.id
                LEFT JOIN predictions p ON o.id = p.id
            """).fetchone()
            expected = detection.confusion({row["labevent_id"] for row in inventory}, injected, ids)
            for name, count in zip(detection.COUNT_KEYS, actual_counts, strict=True):
                compare(f"observation_{method}_{name}", expected[name], count)

        if map_truth:
            keys = {mapping_key(row) for row in inventory}
            truth = {mapping_key(row) for row in map_truth if row["is_error"]}
            flags = {
                mapping_key(finding.identifier) for finding in semantic_findings
                if finding.entity == "mapping" and finding.severity == "error"
            }
            connection.execute("""
                CREATE TABLE mappings (batch VARCHAR, itemid INT);
                CREATE TABLE map_truth (batch VARCHAR, itemid INT);
                CREATE TABLE map_findings (batch VARCHAR, itemid INT);
            """)
            connection.executemany("INSERT INTO mappings VALUES (?, ?)", sorted(keys))
            connection.executemany("INSERT INTO map_truth VALUES (?, ?)", sorted(truth))
            if flags:
                connection.executemany("INSERT INTO map_findings VALUES (?, ?)", sorted(flags))
            actual = connection.execute("""
                SELECT count(*) FROM mappings JOIN map_truth USING (batch, itemid)
                JOIN map_findings USING (batch, itemid)
            """).fetchone()[0]
            compare("mapping_semantic_tp", detection.confusion(keys, truth, flags)["tp"], actual)

        connection.execute("""
            CREATE TABLE lab (patient BIGINT, code VARCHAR, unit VARCHAR, value DOUBLE);
            CREATE TABLE factors (code VARCHAR, analyte VARCHAR, unit VARCHAR, factor DOUBLE);
        """)
        connection.executemany("INSERT INTO lab VALUES (?, ?, ?, ?)", [
            (row["subject_id"], row["loinc"], row["unit"], row["value"]) for row in integrated
        ])
        connection.executemany("INSERT INTO factors VALUES (?, ?, ?, ?)", [
            (code, term["analyte"], unit, factor)
            for code, term in registry["terms"].items()
            for unit, factor in registry["profiles"][term["analyte"]]["to_canonical"].items()
        ])
        for analyte, avg, med, patients in connection.execute("""
            SELECT analyte, avg(value * factor), median(value * factor), count(DISTINCT patient)
            FROM lab JOIN factors USING (code, unit)
            WHERE isfinite(value * factor)
            GROUP BY analyte ORDER BY analyte
        """).fetchall():
            expected = impact.summarize(numeric_rows[analyte])
            for name, value in (("mean", avg), ("median", med), ("patients", patients)):
                compare(f"{analyte}_integrated_{name}", expected[name], value)
    return checks


def save_figure(fig):
    stream = io.BytesIO()
    fig.savefig(stream, format="png", dpi=145, facecolor="white")
    plt.close(fig)
    return stream.getvalue()


def recall_figure(rows):
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), sharey=True, layout="constrained")
    for scenario, ax in zip(SCENARIOS, axes, strict=True):
        for method in ("conventional", "semantic"):
            for policy, style, marker in (("error_only", "-", "o"), ("include_review", "--", "s")):
                selected = [
                    row for row in rows if row["scenario"] == scenario and row["method"] == method
                    and row["policy"] == policy
                ]
                x = [100 * float(row["target_rate"]) for row in selected]
                y = [100 * float(row["recall"]) for row in selected]
                lows = [100 * float(row["recall_seed_min"]) for row in selected]
                highs = [100 * float(row["recall_seed_max"]) for row in selected]
                ax.fill_between(x, lows, highs, color=COLORS[method], alpha=0.08)
                ax.plot(x, y, style, marker=marker, markersize=4, color=COLORS[method],
                        label=f"{method.title()} · {'errors' if policy == 'error_only' else 'incl. reviews'}")
        ax.set(title=SCENARIOS[scenario], xlabel="Target corruption rate (%)",
               xticks=[2.5, 5, 15], ylim=(-4, 105))
        ax.grid(axis="y", alpha=.22)
    axes[0].set_ylabel("Pooled observation recall (%)")
    axes[0].legend(loc="center right", fontsize=7, frameon=False)
    fig.suptitle("Tier 3 detection across ten seeds per setting\nShading shows the per-seed recall range")
    return save_figure(fig)


def distortion_figure(rows):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.0), sharey=True, layout="constrained")
    for scenario, ax in zip(SCENARIOS, axes, strict=True):
        for order, stage in enumerate(("integrated", "conventional", "semantic")):
            lookup = {row["analyte"]: row for row in rows if row["scenario"] == scenario and row["stage"] == stage}
            values = [100 * float(lookup[analyte]["mean_relative_distortion_seed_median"]) for analyte in ANALYTES]
            ax.bar([i + (order - 1) * .23 for i in range(4)], values, width=.23,
                   color=COLORS[stage], label=stage.title())
        ax.set(title=SCENARIOS[scenario], xticks=range(4),
               xticklabels=[name.title() for name in ANALYTES], yscale="symlog")
        ax.tick_params(axis="x", labelrotation=25)
        ax.grid(axis="y", alpha=.22)
    axes[0].set_ylabel("Absolute mean distortion (%)\nSymmetric log scale")
    axes[-1].legend(frameon=False, fontsize=8)
    fig.suptitle("Tier 3 mean distortion at a 5% target\nMedian of ten runs for each analyte and stage")
    return save_figure(fig)


def retention_figure(rows):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8), layout="constrained")
    for analyte, color in zip(ANALYTES, ("#4A708B", "#B54B31", "#368473", "#756298"), strict=True):
        selected = [row for row in rows if row["analyte"] == analyte]
        x = [100 * float(row["target_rate"]) for row in selected]
        for ax, metric, scale in zip(axes, ("source_analyte_retention_seed_median", "patient_count_seed_median"),
                                     (100, 1), strict=True):
            ax.plot(x, [scale * float(row[metric]) for row in selected], "-o", markersize=4,
                    color=color, label=analyte.title())
    for ax in axes:
        ax.set(xlabel="Target mapping removal rate (%)", xticks=[2.5, 5, 15])
        ax.grid(alpha=.22)
    axes[0].set_ylabel("Source observations retained (%)")
    axes[1].set_ylabel("Patients with a numeric result")
    axes[1].legend(frameon=False, fontsize=8)
    fig.suptitle("Scenario C coverage after integration\nMedian across ten seeds per setting")
    return save_figure(fig)


def aggregate_and_plot(files):
    aggregate = {}
    with tempfile.TemporaryDirectory() as temporary, duckdb.connect() as connection:
        directory = Path(temporary)
        for table, sql_name in (("detection", "detection"), ("impact", "impact")):
            raw, output = directory / f"{table}.csv", directory / f"{table}_summary.csv"
            raw.write_bytes(files[raw.name])
            connection.read_csv(str(raw), header=True).create_view(f"{table}_runs")
            query = (ROOT / "sql" / f"evaluation_{sql_name}_summary.sql").read_text().strip().rstrip(";")
            connection.sql(query).write_csv(str(output), header=True)
            aggregate[output.name] = output.read_bytes()

    detection_rows = list(csv.DictReader(io.StringIO(aggregate["detection_summary.csv"].decode())))
    impact_rows = list(csv.DictReader(io.StringIO(aggregate["impact_summary.csv"].decode())))
    aggregate["figures/tier3_detection.png"] = recall_figure([
        row for row in detection_rows
        if row["tier"] == "3" and row["entity"] == "observation" and row["subtype"] == "all"
        and float(row["target_rate"]) > 0
    ])
    aggregate["figures/mean_distortion.png"] = distortion_figure([
        row for row in impact_rows if row["tier"] == "3" and float(row["target_rate"]) == 0.05
        and row["stage"] != "reference"
    ])
    aggregate["figures/omission_retention.png"] = retention_figure([
        row for row in impact_rows if row["tier"] == "3" and row["scenario"] == "C"
        and row["stage"] == "integrated" and float(row["target_rate"]) > 0
    ])
    return aggregate
