"""Paired conditional bootstrap with patients as the resampling units."""

from collections import defaultdict

import numpy as np

from semantic_quality.detection import COUNT_KEYS, METRICS, metrics_from_counts


def patient_weights(inventory, replicates, seed):
    patients = {}
    for row in inventory:
        patient, batch = row["subject_id"], row["batch_id"]
        if patients.setdefault(patient, batch) != batch:
            raise ValueError("A patient occurs in multiple simulated batches")
    index = {patient: i for i, patient in enumerate(sorted(patients))}
    batches = defaultdict(list)
    for patient, i in index.items():
        batches[patients[patient]].append(i)
    rng = np.random.default_rng(seed)
    weights = np.zeros((replicates, len(index)), dtype=np.int32)
    for batch in sorted(batches):
        members = batches[batch]
        count = len(members)
        # A multinomial draw counts how often each patient was selected in this batch.
        weights[:, members] = rng.multinomial(count, np.full(count, 1 / count), size=replicates)
    return index, weights


def conditional_interval(point, values):
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    lower, upper = (np.percentile(finite, [2.5, 97.5]) if len(finite) else (None, None))
    return {"estimate": point, "lower_95": lower, "upper_95": upper, "valid_replicates": len(finite)}


def detection_bootstrap(inventory, positives, predictions, index, weights):
    summaries = {}
    for method, predicted in predictions.items():
        contributions = np.zeros((len(index), len(COUNT_KEYS)), dtype=int)
        for row in inventory:
            key = row["labevent_id"]
            if key in positives:
                cell = "tp" if key in predicted else "fn"
            else:
                cell = "fp" if key in predicted else "tn"
            contributions[index[row["subject_id"]], COUNT_KEYS.index(cell)] += 1
        point = metrics_from_counts(*contributions.sum(axis=0))
        draws = [metrics_from_counts(*row) for row in weights @ contributions]
        summaries[method] = point, draws
    baseline, base_draws = summaries["conventional"]
    semantic, sem_draws = summaries["semantic"]
    return [
        {
            "metric": name,
            **conditional_interval(
                semantic[name] - baseline[name] if semantic[name] is not None and baseline[name] is not None else None,
                [actual[name] - control[name]
                 if actual[name] is not None and control[name] is not None else None
                 for actual, control in zip(sem_draws, base_draws, strict=True)],
            ),
        }
        for name in METRICS
    ]


def weighted_statistics(rows, index, weights):
    if not rows:
        missing = np.full(len(weights), np.nan)
        return {"mean": missing, "median": missing, "patient_weighted_mean": missing,
                "patients": np.zeros(len(weights))}
    sorted_rows = sorted(rows, key=lambda row: row[2])
    values = np.array([value for _, _, value in sorted_rows])
    patients = np.array([index[patient] for _, patient, _ in sorted_rows])
    counts = np.bincount(patients, minlength=len(index))
    sums = np.bincount(patients, weights=values, minlength=len(index))
    recorded = counts > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        means = (weights @ sums) / (weights @ counts)
        patient_means = (weights[:, recorded] @ (sums[recorded] / counts[recorded])) / (
            weights @ recorded.astype(int)
        )
    # Weighted positions give the same median as duplicating all rows for sampled patients.
    cumulative = np.cumsum(weights[:, patients], axis=1, dtype=np.int32)
    total = cumulative[:, -1]
    left = np.argmax(cumulative > ((total - 1) // 2)[:, None], axis=1)
    right = np.argmax(cumulative > (total // 2)[:, None], axis=1)
    medians = np.where(total > 0, (values[left] + values[right]) / 2, np.nan)
    return {"mean": means, "median": medians, "patient_weighted_mean": patient_means,
            "patients": weights @ recorded.astype(int)}
