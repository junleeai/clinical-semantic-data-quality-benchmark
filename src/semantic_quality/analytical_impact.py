"""Apply quarantine and compare canonicalized datasets without repairing values."""

from collections import defaultdict
from statistics import fmean, median

from semantic_quality.detection import ratio
from semantic_quality.validation_models import mapping_key, numeric


def quarantine(rows, observation_errors, mapping_errors):
    return {
        row["labevent_id"] for row in rows
        if row["labevent_id"] in observation_errors or mapping_key(row) in mapping_errors
    }


def canonical_value(row, registry):
    """Interpret the delivered code and reported unit as an analytics consumer would."""
    term = registry["terms"].get(row["loinc"])
    if term is None or not numeric(row["value"]):
        return None
    analyte = term["analyte"]
    profile = registry["profiles"][analyte]
    factor = profile["to_canonical"].get(row["unit"])
    if factor is None:
        return None
    value = row["value"] * factor
    return (analyte, value) if numeric(value) else None


def numerical_rows(rows, registry):
    result = defaultdict(list)
    for row in rows:
        quantity = canonical_value(row, registry)
        if quantity is not None:
            analyte, value = quantity
            result[analyte].append((row["labevent_id"], row["subject_id"], value))
    return result


def summarize(rows):
    patient_values = defaultdict(list)
    for _, patient, value in rows:
        patient_values[patient].append(value)
    values = [value for _, _, value in rows]
    return {
        "observations": len(values),
        "patients": len(patient_values),
        "mean": fmean(values) if values else None,
        "median": median(values) if values else None,
        "patient_weighted_mean": (
            fmean(fmean(group) for group in patient_values.values()) if patient_values else None
        ),
    }


def distortion(current, reference):
    output = {}
    for metric in ("mean", "median", "patient_weighted_mean"):
        value, baseline = current[metric], reference[metric]
        difference = None if value is None or baseline is None else value - baseline
        output[f"{metric}_difference"] = difference
        output[f"{metric}_absolute_distortion"] = abs(difference) if difference is not None else None
        output[f"{metric}_relative_distortion"] = (
            ratio(abs(difference), abs(baseline)) if difference is not None else None
        )
    return output


def summarize_stage(analyte, units, numeric_rows, reference_stats, source_ids, injected, integrated, removed):
    """Report coded-analyte summaries alongside source-analyte retention and triage."""
    current = summarize(numeric_rows)
    clean_present = (source_ids - injected) & integrated
    corrupt = source_ids & injected
    corrupt_present = corrupt & integrated
    source_present = source_ids & integrated
    available = source_present - removed
    numeric_ids = {key for key, _, _ in numeric_rows}
    return {
        "analyte": analyte, "canonical_unit": units[analyte],
        **current, **distortion(current, reference_stats),
        "patient_difference": current["patients"] - reference_stats["patients"],
        "coded_observation_ratio": ratio(current["observations"], reference_stats["observations"]),
        "source_reference_count": len(source_ids),
        "source_physically_available": len(available),
        "source_absent_at_integration": len(source_ids - integrated),
        "source_quarantined": len(source_present & removed),
        "source_still_coded_as_analyte": len(source_ids & numeric_ids),
        "source_analyte_retention": ratio(len(source_ids & numeric_ids), len(source_ids)),
        "clean_integrated": len(clean_present),
        "clean_quarantined": len(clean_present & removed),
        "clean_quarantined_rate": ratio(len(clean_present & removed), len(clean_present)),
        "injected_observations": len(corrupt),
        "corrupted_integrated": len(corrupt_present),
        "corrupted_retained": len(corrupt_present - removed),
        "corrupted_retained_rate": ratio(len(corrupt_present - removed), len(corrupt)),
        "corrupted_retained_among_present_rate": ratio(len(corrupt_present - removed), len(corrupt_present)),
    }
