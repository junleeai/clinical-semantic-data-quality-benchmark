"""Score distinct observation IDs or mapping keys against private labels."""

from collections import defaultdict

POLICIES = {"error_only": {"error"}, "include_review": {"error", "review"}}
METRICS = ("precision", "recall", "f1", "false_positive_rate")
COUNT_KEYS = ("tp", "fp", "tn", "fn")


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def metrics_from_counts(tp, fp, tn, fn):
    return {
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "false_positive_rate": ratio(fp, fp + tn),
    }


def confusion(universe, positives, predicted):
    positives = universe & positives
    negatives = universe - positives
    return {
        "tp": len(positives & predicted),
        "fp": len(negatives & predicted),
        "tn": len(negatives - predicted),
        "fn": len(positives - predicted),
    }


def entity_key(row, entity):
    if entity == "observation":
        return row.get("labevent_id")
    if "batch_id" in row and "itemid" in row:
        return row["batch_id"], row["itemid"]
    return None


def findings_by_severity(findings, entity, universe):
    keys = {"error": set(), "review": set()}
    unjoinable = set()
    for finding in findings:
        if finding.entity != entity:
            continue
        key = entity_key(finding.identifier, entity)
        if key in universe:
            keys[finding.severity].add(key)
        else:
            unjoinable.add(tuple(sorted(finding.identifier.items())))
    return keys, len(unjoinable)


def positive_groups(universe, changes, entity):
    """A subtype's negatives are all clean records. Other injected subtypes are excluded."""
    subtypes = defaultdict(set)
    positives, clean_controls = set(), defaultdict(set)
    for row in changes:
        key = entity_key(row, entity)
        if key not in universe:
            raise ValueError("Ground-truth key is outside the declared evaluation universe")
        if row["is_error"]:
            positives.add(key)
            subtypes[row["subtype"]].add(key)
            payload = row["corrupted"]
            if entity == "observation" and row["scenario"] == "A" and payload is not None:
                lower, upper = payload["lower_bound"], payload["upper_bound"]
                if lower is not None and upper is not None and lower <= payload["value"] <= upper:
                    subtypes["corrupted_within_displayed_bounds"].add(key)
                    if row["subtype"] == "wrong_factor":
                        subtypes["wrong_factor_within_displayed_bounds"].add(key)
        else:
            clean_controls[row["subtype"]].add(key)

    clean = universe - positives
    return [
        ("all", universe, positives),
        *((name, clean | subtypes[name], subtypes[name]) for name in sorted(subtypes)),
        *((name, clean_controls[name], set()) for name in sorted(clean_controls)),
    ]


def score_groups(groups, flags, unjoinable, unavailable_reason):
    for name, universe, positives in groups:
        for policy, severities in POLICIES.items():
            predicted = set.union(*(flags[severity] for severity in severities))
            counts = (dict.fromkeys(COUNT_KEYS) if unavailable_reason
                      else confusion(universe, positives, predicted))
            metrics = (dict.fromkeys(METRICS) if unavailable_reason else metrics_from_counts(**counts))
            review = universe & flags["review"]
            yield {
                "subtype": name, "policy": policy,
                "available": not unavailable_reason, "unavailable_reason": unavailable_reason,
                "eligible_count": len(universe), "injected_count": len(positives),
                "reviewed_count": None if unavailable_reason else len(review),
                "review_only_count": None if unavailable_reason else len(review - flags["error"]),
                "review_workload_rate": None if unavailable_reason else ratio(len(review), len(universe)),
                "unjoinable_identifiers_run": unjoinable if name == "all" else None,
                **counts, **metrics,
            }
