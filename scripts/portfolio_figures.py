"""Render publication-facing figures from identifier-free benchmark tables."""

import csv
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "results" / "audit"
BENCHMARK = ROOT / "results" / "phase-5"
FIGURES = ROOT / "results" / "figures"
INK, BLUE, RUST, GRAY = "#172b42", "#24658b", "#a74129", "#6f7882"
METHODS = ("conventional", "semantic")
SCENARIOS = ("A", "B", "C")

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
    "axes.labelcolor": INK, "axes.titlecolor": INK, "axes.spines.top": False,
    "axes.spines.right": False, "savefig.facecolor": "white",
})


def read(path):
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def save(figure, name):
    figure.savefig(FIGURES / name, dpi=155)
    plt.close(figure)


def cell_chart(ax, x_labels, y_labels, rates, labels):
    colors = plt.colormaps["Blues"].copy()
    colors.set_bad("#ededed")
    ax.imshow(np.ma.masked_invalid(rates), cmap=colors, vmin=0, vmax=1, aspect="auto")
    ax.set(xticks=range(len(x_labels)), xticklabels=x_labels,
           yticks=range(len(y_labels)), yticklabels=y_labels)
    ax.tick_params(length=0, pad=8)
    for i, row in enumerate(rates):
        for j, rate in enumerate(row):
            ax.text(j, i, labels[i][j], ha="center", va="center",
                    color="white" if rate >= .60 else INK, fontsize=9, weight="bold")
    ax.set_xticks(np.arange(len(x_labels) + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(len(y_labels) + 1) - 0.5, minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", length=0)


def evidence_figure(rows):
    lookup = {
        (r["scenario"], r["tier"], r["entity"], r["method"], r["policy"]): r for r in rows
    }
    keys = [(scenario, method) for scenario in SCENARIOS for method in METHODS]
    y_labels = [f"{scenario}  {method.title()}" for scenario, method in keys]
    rates, labels = [], []
    for scenario, method in keys:
        entries = [lookup.get((scenario, tier, "observation", method, "error_only")) for tier in "123"]
        rates.append([float(r["recall"]) if r else np.nan for r in entries])
        labels.append([f'{float(r["recall"]):.1%}' if r else "Unavailable" for r in entries])
    fig, ax = plt.subplots(figsize=(9.8, 4.5))
    fig.subplots_adjust(left=.22, right=.97, bottom=.17, top=.80)
    fig.suptitle("Where does error detection improve?", y=.96, fontsize=17, weight="bold")
    ax.set_title("Observation recall · error-only · 90 perturbed runs pooled across 2.5%, 5%, and 15%",
                 fontsize=10, pad=12)
    cell_chart(ax, ["Tier 1\nOutput only", "Tier 2\nUpstream evidence", "Tier 3\nTrusted registry"],
               y_labels, rates, labels)
    fig.text(.22, .027, "A  Unit and value errors     B  Incorrect mappings     C  Incomplete mappings",
             fontsize=9, color=GRAY)
    save(fig, "recall-by-evidence.png")


def mapping_figure(rows):
    lookup = {
        (r["scenario"], r["entity"], r["method"], r["policy"]): r for r in rows if r["tier"] == "3"
    }
    keys = [(scenario, entity) for scenario in ("B", "C") for entity in ("observation", "mapping")]
    columns = [("conventional", "error_only"), ("semantic", "error_only"), ("semantic", "include_review")]
    labels, rates, y_labels = [], [], []
    for scenario, entity in keys:
        entries = [lookup[scenario, entity, method, policy] for method, policy in columns]
        denominator = int(entries[0]["tp"]) + int(entries[0]["fn"])
        y_labels.append(f"{scenario}  {entity.title()}\n{denominator:,} injected")
        rates.append([float(row["recall"]) for row in entries])
        labels.append([f'{int(row["tp"]):,} / {denominator:,}\n{float(row["recall"]):.1%}' for row in entries])
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    fig.subplots_adjust(left=.19, right=.97, bottom=.20, top=.81)
    fig.suptitle("Mapping entries and affected observations", y=.96, fontsize=17, weight="bold")
    ax.set_title("Tier 3 · 60 perturbed B/C runs pooled across 2.5%, 5%, and 15%", fontsize=10, pad=12)
    cell_chart(ax, ["Conventional\nErrors", "Semantic\nErrors", "Semantic\nErrors + reviews"], y_labels, rates, labels)
    fig.text(.19, .055, "Cells show true positives / injected errors. Conventional review-inclusive counts are identical.",
             fontsize=9, color=GRAY)
    save(fig, "mapping-and-observation.png")


def failure_figure(runs, subtypes):
    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 4.9))
    fig.subplots_adjust(left=.075, right=.98, bottom=.20, top=.79, wspace=.48)
    fig.suptitle("Creatinine mean distortion increased after quarantine", y=.96, fontsize=17, weight="bold")
    runs = sorted(runs, key=lambda row: int(row["seed"]))
    x = range(len(runs))
    before = [100 * float(row["integrated_relative_mean_distortion"]) for row in runs]
    after = [100 * float(row["semantic_relative_mean_distortion"]) for row in runs]
    differences = [post - pre for pre, post in zip(before, after, strict=True)]
    left.bar(x, differences, color=[BLUE if int(row["seed"]) == 42 else RUST for row in runs], width=.74)
    left.set(title=f"Increase in absolute mean distortion\nMedian distortion {median(before):.2f}% → {median(after):.2f}%",
             ylabel="Change (percentage points)", xlabel="Corruption seed",
             xticks=x, xticklabels=[row["seed"] for row in runs], ylim=(0, max(differences) * 1.16))
    left.grid(axis="y", alpha=.22)
    anchor = {row["subtype"]: row for row in subtypes if row["seed"] == "42"}
    categories = ("label_only", "stale_label", "value_only", "wrong_factor")
    y = np.arange(4)
    for label, field, offset, color in (
        ("Integrated", "integrated_sum_of_value_changes_mg_dl", -.16, GRAY),
        ("After semantic quarantine", "retained_sum_of_value_changes_mg_dl", .16, BLUE),
    ):
        right.barh(y + offset, [float(anchor[key][field]) for key in categories],
                   height=.30, color=color, label=label)
    right.axvline(0, color=INK, linewidth=.7)
    right.set(title="Source of the error at seed 42\nThe 38 label-only rows were quarantined",
              xlabel="Sum of value changes from clean (mg/dL)",
              yticks=y, yticklabels=["Label only", "Stale label", "Value only", "Wrong factor"])
    right.invert_yaxis()
    right.legend(loc="lower right", fontsize=8, frameon=False)
    right.grid(axis="x", alpha=.22)
    fig.text(.075, .06, "Scenario A · 5% target · Tier 3 · error-only quarantine · 3,003 reference observations per seed",
             fontsize=9, color=GRAY)
    save(fig, "creatinine-quarantine.png")


def uncertainty_figure(intervals, rows):
    anchors = {r["scenario"]: r for r in intervals if r["metric"] == "recall" and r["target_rate"] == "0.05"}
    scores = {}
    for r in rows:
        if (r["entity"], r["tier"], r["policy"], r["subtype"], r["target_rate"]) == (
            "observation", "3", "error_only", "all", "0.05",
        ):
            scores[r["scenario"], r["seed"], r["method"]] = float(r["recall"])
    fig, (left, right) = plt.subplots(1, 2, sharey=True, figsize=(10, 4.2))
    fig.subplots_adjust(left=.13, right=.97, bottom=.21, top=.79, wspace=.18)
    fig.suptitle("Patient-resampling uncertainty and corruption-seed variation", y=.96, fontsize=15, weight="bold")
    for y, scenario in enumerate(SCENARIOS):
        estimate, low, high = (100 * float(anchors[scenario][key]) for key in ("estimate", "lower_95", "upper_95"))
        left.hlines(y, low, high, color=BLUE, linewidth=2)
        left.plot(estimate, y, "o", color=BLUE)
        seeds = sorted({seed for s, seed, _ in scores if s == scenario})
        spread = [100 * (scores[scenario, seed, "semantic"] - scores[scenario, seed, "conventional"]) for seed in seeds]
        right.plot(spread, [y] * len(spread), "o", color=RUST, alpha=.65, markersize=5)
    left.set(title="Seed 42 · conditional 95% interval\n399 draws of 100 patients", yticks=range(3),
             yticklabels=["A  Units", "B  Mappings", "C  Omissions"], ylim=(2.5, -.5))
    right.set_title("Ten corruption seeds · one dot per run")
    for ax in (left, right):
        ax.set(xlim=(-3, 103), xticks=[0, 25, 50, 75, 100], xlabel="Recall gain (percentage points)")
        ax.grid(axis="x", alpha=.22)
    fig.text(.13, .055, "Semantic minus conventional · 5% target · Tier 3 · error-only. Overlapping seed dots coincide.",
             fontsize=9, color=GRAY)
    save(fig, "recall-uncertainty.png")


def main():
    FIGURES.mkdir(exist_ok=True)
    pooled = read(AUDIT / "pooled_detection.csv")
    evidence_figure(pooled)
    mapping_figure(pooled)
    failure_figure(read(AUDIT / "creatinine_runs.csv"), read(AUDIT / "creatinine_subtypes.csv"))
    uncertainty_figure(read(BENCHMARK / "detection_intervals.csv"), read(BENCHMARK / "detection.csv"))


if __name__ == "__main__":
    main()
