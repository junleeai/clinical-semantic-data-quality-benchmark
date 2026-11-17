"""Shared structural and reconciliation checks used by both methods."""

from collections import Counter, defaultdict

from semantic_quality.validation_models import (
    FIELD_CHECKS, GENERIC_MAX, IDENTITY, OBSERVATION_FIELDS, REQUIRED, integer_id,
    loinc_shape, mapping_identifier, mapping_key, numeric, valid_observation_id,
)


def structure(observations, report):
    counts = Counter(row["labevent_id"] for row in observations if integer_id(row.get("labevent_id")))
    for event_id, count in counts.items():
        if count > 1:
            report("observation", {"labevent_id": event_id}, "duplicate_observation_id", "error",
                   "Multiple output rows share the same observation ID.", {"count": count}, "quarantine")
    for line, row in enumerate(observations, 1):
        identifier = valid_observation_id(row, line)
        missing_columns = sorted(set(OBSERVATION_FIELDS) - row.keys())
        unexpected_columns = sorted(row.keys() - set(OBSERVATION_FIELDS))
        if missing_columns or unexpected_columns:
            report("observation", identifier, "observation_schema", "error",
                   "Output row differs from the declared observation schema.",
                   {"missing_columns": missing_columns, "unexpected_column_count": len(unexpected_columns)},
                   "quarantine")
        missing_values = [field for field in REQUIRED if field in row and (
            row[field] is None or isinstance(row[field], str) and not row[field].strip()
        )]
        if missing_values:
            report("observation", identifier, "required_value_missing", "error",
                   "Required fields are blank or null.", {"fields": missing_values}, "quarantine")
        bad_fields = [field for field, check in FIELD_CHECKS.items()
                      if field in row and row[field] is not None
                      and field not in missing_values and not check(row[field])]
        if bad_fields:
            report("observation", identifier, "observation_field_type", "error",
                   "Fields violate identifier, timestamp, code syntax, or finite-number rules.",
                   {"fields": sorted(bad_fields)}, "quarantine")
        value = row.get("value")
        if numeric(value) and not 0 < value <= GENERIC_MAX:
            report("observation", identifier, "generic_concentration_review", "review",
                   "Value is outside the broad screening range for this positive concentration feed.",
                   {"value": value, "exclusive_minimum": 0, "inclusive_maximum": GENERIC_MAX}, "manual_review")
        lower, upper = row.get("lower_bound"), row.get("upper_bound")
        if numeric(lower) and numeric(upper) and lower > upper:
            report("observation", identifier, "reference_bounds_reversed", "error",
                   "The lower reference bound exceeds the upper bound.",
                   {"lower_bound": lower, "upper_bound": upper}, "review_bounds")


def reconcile(evidence, report):
    inventory = defaultdict(list)
    outputs = defaultdict(list)
    for row in evidence.inventory:
        inventory[row["labevent_id"]].append(row)
    for row in evidence.observations:
        if integer_id(row.get("labevent_id")):
            outputs[row["labevent_id"]].append(row)
    # Comparing ID sets is the Python equivalent of a SQL anti-join.
    for event_id in inventory.keys() - outputs.keys():
        report("observation", {"labevent_id": event_id}, "source_observation_missing", "error",
               "An upstream observation is absent from the integrated output.",
               {"source_rows": len(inventory[event_id]), "output_rows": 0}, "reconcile")
    for event_id in outputs.keys() - inventory.keys():
        report("observation", {"labevent_id": event_id}, "unexpected_output_observation", "error",
               "An integrated observation lacks an upstream inventory entry.",
               {"output_rows": len(outputs[event_id]), "source_rows": 0}, "quarantine")
    for event_id, source_rows in inventory.items():
        identifier = {"labevent_id": event_id}
        if len(source_rows) > 1:
            report("observation", identifier, "duplicate_inventory_id", "error",
                   "Upstream identity is ambiguous because the inventory repeats this ID.",
                   {"count": len(source_rows)}, "reconcile")
            continue
        if len(outputs.get(event_id, ())) == 1:
            output = outputs[event_id][0]
            source = source_rows[0]
            differences = sorted(
                field for field in IDENTITY
                if FIELD_CHECKS[field](output.get(field)) and output[field] != source[field]
            )
            if differences:
                report("observation", identifier, "source_identity_mismatch", "error",
                       "Output identity fields disagree with the upstream record for this ID.",
                       {"fields": differences}, "quarantine")

    expected = Counter(mapping_key(row) for row in evidence.inventory)
    observed = Counter(mapping_key(row) for row in evidence.feed_mappings)
    usable = {mapping_key(row) for row in evidence.feed_mappings if loinc_shape(row.get("loinc"))}
    for row in evidence.feed_mappings:
        if not loinc_shape(row.get("loinc")):
            report("mapping", mapping_identifier(mapping_key(row)), "invalid_feed_target", "error",
                   "The feed target is missing or does not have LOINC code syntax.",
                   {"field": "loinc"}, "restore_mapping")
    output_keys = Counter(
        mapping_key(row) for row in evidence.observations
        if FIELD_CHECKS["batch_id"](row.get("batch_id")) and integer_id(row.get("itemid"))
    )
    for key in expected.keys() - usable:
        report("mapping", mapping_identifier(key), "required_feed_mapping_missing", "error",
               "Upstream observations have no usable mapping for their batch and source item.",
               {"upstream_observations": expected[key]}, "restore_mapping")
    for key in observed.keys() - expected.keys():
        report("mapping", mapping_identifier(key), "unused_feed_mapping", "review",
               "A batch mapping has no matching key in the supplied inventory.",
               {"mapping_rows": observed[key]}, "manual_review")
    for key, count in observed.items():
        if count > 1:
            report("mapping", mapping_identifier(key), "duplicate_feed_mapping", "error",
                   "Multiple feed mappings use the same batch and source item.",
                   {"count": count}, "reconcile")
    for key in output_keys.keys() - usable:
        report("mapping", mapping_identifier(key), "output_without_feed_mapping", "error",
               "Integrated rows reference a batch and source item with no usable feed mapping.",
               {"output_observations": output_keys[key]}, "reconcile")


def registry_membership(evidence, report):
    registry = evidence.registry
    records = (
        ("observation", evidence.observations, valid_observation_id),
        ("mapping", evidence.feed_mappings, lambda row, line: mapping_identifier(mapping_key(row))),
    )
    for entity, rows, identify in records:
        for line, row in enumerate(rows, 1):
            identifier = identify(row, line)
            itemid, code = row.get("itemid"), row.get("loinc")
            if integer_id(itemid) and str(itemid) not in registry["sources"]:
                report(entity, identifier, "source_item_outside_registry", "review",
                       "The source item is outside this registry's reviewed scope.",
                       {"itemid": itemid}, "manual_review")
            if loinc_shape(code) and code not in registry["terms"]:
                report(entity, identifier, "target_code_outside_registry", "review",
                       "The target code is outside this local terminology registry's coverage.",
                       {"loinc": code}, "manual_review")
