"""Generate one controlled scenario from the frozen numeric cohort."""

import argparse
import logging
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from semantic_quality.ingestion import ROOT
from semantic_quality.reference import LabMapping, Observation, load_mappings, read_reference
from semantic_quality.snapshots import fingerprint, json_bytes, jsonl_bytes, publish_snapshot

SCENARIOS = ROOT / "data" / "processed" / "scenarios"
DESIGN_VERSION = "phase3-v1"
UNIT_ERRORS = ("label_only", "value_only", "stale_label", "wrong_factor")
MAPPING_ERRORS = ("same_unit_analyte_swap", "wrong_specimen")
WRONG_FACTOR_MULTIPLIER = 1.10
LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunSettings:
    scenario: str
    seed: int
    rate: Decimal
    control_rate: Decimal
    batches: int

    def __post_init__(self):
        if self.scenario not in {"A", "B", "C"}:
            raise ValueError("Scenario must be A, B, or C")
        for rate in (self.rate, self.control_rate):
            if not rate.is_finite() or not 0 <= rate <= 1:
                raise ValueError("Rates must be finite and between 0 and 1")
        if self.scenario != "A" and self.control_rate:
            raise ValueError("The alternate-unit control rate applies only to Scenario A")
        if self.batches < 2:
            raise ValueError("At least two simulated batches are required")


def assign_batches(rows: tuple[Observation, ...], count: int) -> dict[int, str]:
    patients = {row.subject_id for row in rows}
    if count > len(patients):
        raise ValueError("Number of batches exceeds the number of patients")
    # Round-robin assignment balances patient counts without using the error seed.
    ordered = sorted(patients, key=lambda patient: (fingerprint(str(patient).encode()), patient))
    return {patient: f"F{index % count + 1:03d}" for index, patient in enumerate(ordered)}


def apply_unit_change(row: Observation, mapping: LabMapping, subtype: str) -> Observation:
    scale = mapping.alternate_factor
    if subtype == "label_only":
        return replace(row, unit=mapping.alternate_unit)
    if subtype == "value_only":
        return replace(row, value=row.value * scale)
    if subtype == "stale_label":
        return replace(
            row, value=row.value * scale,
            lower_bound=row.lower_bound * scale, upper_bound=row.upper_bound * scale,
        )
    if subtype in {"wrong_factor", "correct_conversion", "equivalent_unit"}:
        value = row.value * scale
        if subtype == "wrong_factor":
            value *= WRONG_FACTOR_MULTIPLIER
        return replace(
            row, value=value, unit=mapping.alternate_unit, loinc=mapping.alternate_loinc,
            lower_bound=row.lower_bound * scale, upper_bound=row.upper_bound * scale,
        )
    raise ValueError(f"Unknown unit operation: {subtype}")


def unit_operations(rows, mappings, settings, rng) -> tuple[dict[int, str], int]:
    item_rows = defaultdict(list)
    for row in rows:
        item_rows[row.itemid].append(row)
    operations = {}
    eligible_count = 0
    for itemid, observations in sorted(item_rows.items()):
        mapping = mappings[itemid]
        if mapping.alternate_factor != 1:
            # Zero would make a value-only conversion a no-op.
            eligible = [row.labevent_id for row in observations if row.value != 0]
            eligible_count += len(eligible)
            rng.shuffle(eligible)
            for index, key in enumerate(eligible[:int(settings.rate * len(eligible))]):
                operations[key] = UNIT_ERRORS[index % len(UNIT_ERRORS)]
        remaining = [row.labevent_id for row in observations if row.labevent_id not in operations]
        controls = rng.sample(remaining, int(settings.control_rate * len(remaining)))
        control = "equivalent_unit" if mapping.alternate_factor == 1 else "correct_conversion"
        operations.update(dict.fromkeys(controls, control))
    return operations, eligible_count


def mapping_operations(mapping_keys, mappings, settings, rng) -> tuple[dict, int]:
    eligible = list(mapping_keys)
    if settings.scenario == "C":
        keys_by_item = defaultdict(list)
        for key in eligible:
            keys_by_item[key[1]].append(key)
        if any(len(keys) < 2 for keys in keys_by_item.values()) and settings.rate:
            raise ValueError("Scenario C requires each analyte in at least two batches")
        # Keep one mapping per analyte so even the highest rate preserves coverage.
        protected = {rng.choice(keys) for keys in keys_by_item.values()}
        eligible = [key for key in eligible if key not in protected]
    rng.shuffle(eligible)
    operations = {}
    for index, key in enumerate(eligible[:int(settings.rate * len(eligible))]):
        if settings.scenario == "C":
            operations[key] = ("removed_mapping", None)
            continue
        mapping = mappings[key[1]]
        subtype = MAPPING_ERRORS[index % len(MAPPING_ERRORS)]
        code = mappings[mapping.swap_itemid].loinc if subtype == "same_unit_analyte_swap" else mapping.wrong_specimen_loinc
        operations[key] = (subtype, code)
    return operations, len(eligible)


def observation_payload(row: Observation | None) -> dict | None:
    if row is None:
        return None
    return {
        "value": row.value, "unit": row.unit, "loinc": row.loinc,
        "lower_bound": row.lower_bound, "upper_bound": row.upper_bound,
    }


def generate_run(rows: tuple[Observation, ...], mappings: dict[int, LabMapping], settings: RunSettings):
    rows = tuple(sorted(rows, key=lambda row: row.labevent_id))
    patient_batches = assign_batches(rows, settings.batches)
    mapping_keys = sorted({(patient_batches[row.subject_id], row.itemid) for row in rows})
    rng = random.Random(settings.seed)
    unit_changes = {}
    mapping_changes = {}
    if settings.scenario == "A":
        unit_changes, eligible_count = unit_operations(rows, mappings, settings, rng)
    else:
        mapping_changes, eligible_count = mapping_operations(mapping_keys, mappings, settings, rng)

    context = {"scenario": settings.scenario, "seed": settings.seed}
    inventory = []
    integrated = []
    observation_truth = []
    mapping_truth = []
    feed_mappings = []
    for batch_id, itemid in mapping_keys:
        original_code = mappings[itemid].loinc
        subtype, code = mapping_changes.get((batch_id, itemid), (None, original_code))
        key = {"batch_id": batch_id, "itemid": itemid}
        if code is not None:
            feed_mappings.append({**key, "loinc": code})
        if subtype:
            mapping_truth.append({
                **context, **key, "subtype": subtype, "is_error": True,
                "original": {"loinc": original_code},
                "corrupted": {"loinc": code} if code is not None else None,
            })

    for row in rows:
        batch_id = patient_batches[row.subject_id]
        key = {"batch_id": batch_id, "itemid": row.itemid}
        inventory.append({
            **key, "labevent_id": row.labevent_id,
            "subject_id": row.subject_id, "specimen_id": row.specimen_id,
        })
        unit_subtype = unit_changes.get(row.labevent_id)
        mapping_subtype, code = mapping_changes.get((batch_id, row.itemid), (None, row.loinc))
        subtype = unit_subtype or mapping_subtype
        updated = row
        if unit_subtype:
            updated = apply_unit_change(row, mappings[row.itemid], unit_subtype)
        elif mapping_subtype:
            updated = replace(row, loinc=code) if code is not None else None
        if updated is not None:
            integrated.append({**asdict(updated), "batch_id": batch_id})
        if subtype:
            observation_truth.append({
                **context, **key, "labevent_id": row.labevent_id, "subtype": subtype,
                "is_error": subtype not in {"correct_conversion", "equivalent_unit"},
                "original": observation_payload(row), "corrupted": observation_payload(updated),
            })

    private_summary = {
        **context,
        "design_version": DESIGN_VERSION,
        "rate": str(settings.rate.normalize()),
        "control_rate": str(settings.control_rate.normalize()),
        "batches": settings.batches,
        "eligible_unit_observations": eligible_count if settings.scenario == "A" else None,
        "eligible_mapping_entries": eligible_count if settings.scenario != "A" else None,
        "source_observations": len(inventory),
        "output_observations": len(integrated),
        "mapping_entries_before": len(mapping_keys),
        "mapping_entries_after": len(feed_mappings),
        "mapping_entries_changed": len(mapping_truth),
        "affected_observations": sum(entry["is_error"] for entry in observation_truth),
        "observations_by_subtype": dict(Counter(entry["subtype"] for entry in observation_truth)),
        "observations_missing_from_output": len(inventory) - len(integrated),
        "reference_sha256": fingerprint(jsonl_bytes(asdict(row) for row in rows)),
    }
    return {
        "validator_input/observations.jsonl": jsonl_bytes(integrated),
        "validator_input/source_aware/upstream_inventory.jsonl": jsonl_bytes(inventory),
        "validator_input/source_aware/feed_mappings.jsonl": jsonl_bytes(feed_mappings),
        "ground_truth/observation_changes.jsonl": jsonl_bytes(observation_truth),
        "ground_truth/mapping_changes.jsonl": jsonl_bytes(mapping_truth),
        "ground_truth/run.json": json_bytes(private_summary, pretty=True),
    }, private_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=["A", "B", "C"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rate", type=Decimal, default=Decimal("0.05"))
    parser.add_argument("--control-rate", type=Decimal)
    parser.add_argument("--batches", type=int, default=20)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        control_rate = args.control_rate
        if control_rate is None:
            control_rate = Decimal("0.05") if args.scenario == "A" and args.rate > 0 else Decimal(0)
        settings = RunSettings(args.scenario, args.seed, args.rate, control_rate, args.batches)
        files, summary = generate_run(read_reference(), load_mappings(), settings)
        run_id = fingerprint(files["ground_truth/run.json"])[:20]
        destination = SCENARIOS / run_id
        publish_snapshot(destination, files)
    except (InvalidOperation, OSError, ValueError) as error:
        parser.exit(1, f"Scenario generation failed: {error}\n")
    LOG.info(
        "Scenario %s: %s affected observations, %s changed mapping entries, %s omitted observations",
        settings.scenario, summary["affected_observations"], summary["mapping_entries_changed"],
        summary["observations_missing_from_output"],
    )
    LOG.info("Wrote local run to %s", destination)


if __name__ == "__main__":
    main()
