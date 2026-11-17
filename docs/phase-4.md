# Phase 4 validation design

The validator runs conventional and semantic checks on the same evidence object. The semantic method includes the shared conventional checks. In Tier 3 it also interprets terminology and unit relationships. Findings are row- or mapping-level observations about data quality. The code has no scoring or downstream analytics stage.

## Evidence tiers

| Tier | Identical inputs for both methods | Questions the evidence supports |
|---|---|---|
| 1 · Output-only | Integrated `observations.jsonl` and the output schema | Do rows conform to the declared shape and types? Are IDs unique? Are concentration values finite and broadly plausible? |
| 2 · Source-aware | Tier 1 plus the upstream identity inventory and batch feed mappings | Which upstream IDs are absent downstream? Which output IDs or mapping keys lack upstream evidence? Do identities agree? |
| 3 · Registry-aware | Tier 2 plus the frozen terminology and mapping registry | Are the item and target code in the local catalog? Do their meanings, specimens, and units agree? Does the value merit review after normalization? |

Each invocation runs one tier. Tier 1 reads no source-aware files. Tiers 1 and 2 do not read the registry. Phase 3 exports identifiers only in its upstream inventory, so Tier 2 adds reconciliation but cannot recheck conversion arithmetic or establish analyte identity independently of the output. The shared rules therefore yield the same findings for both methods at Tiers 1 and 2. At Tier 3 both methods have registry access. The conventional method checks relational membership. The semantic method also reads the concepts that membership identifies.

Python computes the ID anti-join with set differences. An anti-join is the set of upstream IDs with no match in the integrated output. A second difference finds downstream rows absent upstream. A mapping key is a pair of batch ID and source item ID. Checking that key separately distinguishes a missing mapping from a missing observation, which could also have other causes. Both methods use the same comparisons, and neither changes the inventory.

## Rules and dependencies

| Tier | Rule IDs | Exact inputs and interpretation |
|---|---|---|
| 1 · Shared | `observation_schema`, `required_value_missing`, `observation_field_type` | Output keys must match the contract. Observation, patient, specimen, and source item IDs must be positive integers. Batch and unit must be nonblank text. Time must parse as an ISO datetime. LOINC must have digit-hyphen-digit syntax. Value must be finite and numeric. Bound fields must exist, and their values may be null. |
| 1 · Shared | `duplicate_observation_id` | Count occurrences of each valid output `labevent_id`. |
| 1 · Shared | `generic_concentration_review`, `reference_bounds_reversed` | Screen measured values outside the broad positive concentration envelope (greater than zero and up to 1,000,000 in the reported unit). Check order when both bounds are numeric. The envelope is a structural data screen for this feed. |
| 2 · Shared | `source_observation_missing`, `unexpected_output_observation`, `duplicate_inventory_id`, `source_identity_mismatch` | Compare output and inventory `labevent_id` sets and counts. For one-to-one matches compare batch, item, patient, and specimen IDs. |
| 2 · Shared | `invalid_feed_target`, `required_feed_mapping_missing`, `unused_feed_mapping`, `duplicate_feed_mapping`, `output_without_feed_mapping` | Compare the `(batch_id, itemid)` pairs in inventory, feed mapping, and output. Require a syntactically usable LOINC in the feed mapping. The feed mapping and integrated code can legitimately differ when the result changes quantity property during normalization. |
| 3 · Shared | `source_item_outside_registry`, `target_code_outside_registry` | Check `itemid` and LOINC membership in the local registry for output rows and feed mappings. Missing membership warrants review because the catalog has limited coverage. |
| 3 · Semantic | `analyte_concept_mismatch`, `specimen_class_conflict`, `specimen_mapping_uncertain` | Compare the source registry's analyte and documented fluid class to the target LOINC analyte and specimen system for output rows and feed mappings. Blood-to-urine conflicts are explicit. Blood versus a particular blood-derived matrix can warrant review when it disagrees with the preferred mapping. |
| 3 · Semantic | `concept_unit_conflict`, `unit_outside_registry` | Combine the reported unit, the unit's quantity property, and the coded analyte's supported conversion units. Mass per volume and amount per volume require compatible codes. The monovalent sodium and potassium profiles permit `mEq/L` and `mmol/L` equivalence. |
| 3 · Semantic | `normalized_concentration_review` | Re-express a finite value in the coded analyte's canonical unit and check the analyte's broad upper screening limit. Review outliers and the unit without inferring a conversion error. |

The registry is versioned as **mimic-demo-v2.2-labs-1.0.0**. It describes four reviewed source items and a local subset of LOINC terms with analyte, quantity, and specimen properties. It uses the verified v2.2 dictionary and the published crosswalk review for preferred mappings. The preferred specimen is serum or plasma. The source only establishes `Blood`, so the exact matrix is uncertain. The unit profiles use UCUM conventions and CDC analyte-specific factors. Upper bounds (creatinine 150 mg/dL, glucose 10,000 mg/dL, potassium 30 mmol/L, sodium 200 mmol/L) follow the broad screens used in MIT-LCP's chemistry extraction. They are review triggers, not clinical limits. [Registry and provenance](../configs/validation-registry-v1.json) · [MIMIC dictionary](https://physionet.org/content/mimic-iv-demo/2.2/hosp/d_labitems.csv.gz) · [LOINC property and specimen guidance](https://loinc.org/kb/faq/content) · [UCUM](https://ucum.org/ucum) · [CDC conversions](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2011/DataFiles/BIOPRO_G.htm) · [MIT-LCP screening limits](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/measurement/chemistry.sql)

Normalizing the observed number checks its magnitude under the stated unit. Checking the actual arithmetic would require an independent same-event original value, which none of the tiers include. A plausible value with a compatible code and unit can pass. Bounds are not used as normal/abnormal flags. Genuine abnormal results exist, and the source intervals may depend on missing clinical context.

## Finding format and fabricated examples

Every JSON Lines finding identifies an `entity` and an `identifier`: `labevent_id` for a usable observation ID, a one-based input line for an unusable ID, or the batch and item ID for a mapping. It also includes `rule_id`, `method`, `tier`, `severity`, `explanation`, `evidence`, and `recommended_action`. **Error** identifies a violation of the feed contract or a supported code relationship. **Review** requests investigation of an outlier, missing registry coverage, or uncertainty. Recommended actions are advisory; the command emits findings and leaves the input unchanged.

| Fabricated input | Finding | Action |
|---|---|---|
| Upstream ID 42 is absent from output | Both methods, Tiers 2–3, `source_observation_missing` | Reconcile source and output. |
| Glucose has mass-concentration code `2345-7` with unit `mmol/L` | Semantic, Tier 3, `concept_unit_conflict` | Quarantine pending reconciliation of code and unit. |
| Item 50971 (potassium) carries sodium code `2951-2` | Semantic, Tier 3, `analyte_concept_mismatch` | Review the mapping. |
| Sodium item 50983 uses a whole-blood code | Semantic, Tier 3, `specimen_mapping_uncertain` | Review the matrix with source documentation. |
| Glucose has code `14749-6`, value 5.49549, and unit `mmol/L` | No finding from the stated facts | The fields do not establish the original number. |

## Reproduction and leakage controls

Use the `validator_input` directory printed by the Phase 3 command. Example using the local zero-rate A run:

```sh
mkdir -p data/processed/validation
uv run --locked python -m semantic_quality.validation \
  data/processed/scenarios/1c8bc743be0e1a13a5df/validator_input --tier 3 \
  > data/processed/validation/example-tier-3.jsonl
uv run --locked python -m pytest -q
```

The program opens fixed filenames inside the declared input directory and rejects symlink escapes. The validators consume only the resulting evidence object. They have no generator imports and receive no reference records, run metadata, seeds, corruption manifests, or perturbation configuration. The runner checks the locked validator code hashes and, in Tier 3, the registry hash and version. The frozen lock records version **phase4-1.0.0**. Findings and their identifiers stay under Git-ignored `data/processed/` in the example. [Validation lock](../configs/validation-lock.json)

All **47 tests passed**, including 23 Phase 4 cases. Real Phase 3 inputs were staged without their private directories and replayed across 27 run/tier combinations. Findings matched byte for byte. The clean reference control produced no findings at each tier. These checks establish interface behavior and reproducibility.

## Phase 5 recommendation

Compare methods within the same evidence tier. Use Tier 3 as the primary comparison of rule interpretation and show Tier 1 versus Tier 2 as the effect of adding reconciliation evidence. In a separate evaluator, join findings to the private manifests after validation. Score unique observation IDs and unique mapping keys separately. Use upstream IDs as the observation universe in source-aware omission experiments and report output-only observation omission detection as unavailable. Predeclare how review findings contribute to primary and sensitivity analyses, handle undefined metrics, and preserve the same triage rules across methods. Keep whole patients together in uncertainty estimates, account for batch-wide mapping perturbations, and report seed variability separately. For downstream effects, document how review and quarantine decisions affect retention before comparing summaries. Limits include the narrow registry, absent independent original numeric values, fluid-level specimen metadata, and one hospital's cohort.
