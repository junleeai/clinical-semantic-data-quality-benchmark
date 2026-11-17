"""Interpret source identities, terminology, and units using the trusted registry."""

from semantic_quality.validation_models import (
    integer_id, loinc_shape, mapping_identifier, mapping_key, nonblank, numeric, valid_observation_id,
)


def concept_relationship(entity, identifier, source, code, term, report):
    if source["analyte"] != term["analyte"]:
        report(entity, identifier, "analyte_concept_mismatch", "error",
               "The target concept names a different analyte from the reviewed source item.",
               {"source_analyte": source["analyte"], "target_analyte": term["analyte"], "loinc": code},
               "review_mapping")

    specimen = term["specimen"]
    if source["fluid"] == "blood" and specimen == "urine":
        report(entity, identifier, "specimen_class_conflict", "error",
               "The target term describes urine while the source dictionary describes blood.",
               {"source_fluid": source["fluid"], "target_specimen": specimen, "loinc": code},
               "review_mapping")
    elif specimen != source["preferred_specimen"]:
        report(entity, identifier, "specimen_mapping_uncertain", "review",
               "The target differs from the preferred specimen mapping. The source class cannot resolve the matrix.",
               {"source_fluid": source["fluid"], "preferred_specimen": source["preferred_specimen"],
                "target_specimen": specimen, "loinc": code}, "manual_review")


def concentration(row, term, profile, quantities, identifier, report):
    unit = row.get("unit")
    if not nonblank(unit):
        return
    quantity = quantities.get(unit)
    factor = profile["to_canonical"].get(unit)
    if quantity is None:
        report("observation", identifier, "unit_outside_registry", "review",
               "The reported unit is outside the registry's supported vocabulary.",
               {"unit": unit}, "manual_review")
        return

    # The analyte profiles permit charge concentration only for monovalent Na+ and K+.
    compatible_quantity = quantity == term["quantity"] or (
        quantity == "charge" and term["quantity"] == "molar" and factor is not None
    )
    if factor is None or not compatible_quantity:
        report("observation", identifier, "concept_unit_conflict", "error",
               "The reported unit is incompatible with this coded analyte or quantity property.",
               {"unit": unit, "unit_quantity": quantity, "loinc": row["loinc"],
                "loinc_quantity": term["quantity"], "coded_analyte": term["analyte"]}, "quarantine")
        return

    value = row.get("value")
    if numeric(value) and value > profile["review_max"] / factor:
        report("observation", identifier, "normalized_concentration_review", "review",
               "The converted result exceeds the documented analyte-specific screening limit. Verify the value and unit.",
               {"reported_value": value, "reported_unit": unit, "factor_to_canonical": factor,
                "canonical_unit": profile["unit"], "review_maximum": profile["review_max"]}, "manual_review")


def check_semantics(evidence, report):
    registry = evidence.registry
    records = (
        ("observation", evidence.observations, valid_observation_id),
        ("mapping", evidence.feed_mappings, lambda row, line: mapping_identifier(mapping_key(row))),
    )
    for entity, rows, identify in records:
        for line, row in enumerate(rows, 1):
            itemid, code = row.get("itemid"), row.get("loinc")
            if not integer_id(itemid) or not loinc_shape(code):
                continue
            source = registry["sources"].get(str(itemid))
            term = registry["terms"].get(code)
            if term is None:
                continue
            identifier = identify(row, line)
            if source:
                concept_relationship(entity, identifier, source, code, term, report)
            if entity == "observation":
                profile = registry["profiles"][term["analyte"]]
                concentration(row, term, profile, registry["quantities"], identifier, report)
