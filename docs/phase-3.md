# Phase 3 reference cohort and simulated integration errors

## Frozen reference

The input is the checksum-verified **MIMIC-IV Clinical Database Demo v2.2** loaded in Phase 2. SQL selects the four reviewed `itemid` values, looks up their lab dictionary entries, and confirms a patient match. Every finite `valuenum` for these items enters the numeric cohort. The extraction checks its expected source unit and identity fields and keeps repeat measurements. This yields 11,740 observations from 100 patients. Three potassium rows with missing numeric results go to the local source audit with their original fields. [Dataset release and attribution](https://doi.org/10.13026/dp1f-ex47) · [Phase 2 profile](dataset-profile.md)

| Analyte | Item ID | Included | Source unit | Canonical unit | Canonical LOINC |
|---|---:|---:|---|---|---|
| Creatinine | 50912 | 3,003 | mg/dL | mg/dL | [2160-0](https://loinc.org/2160-0) |
| Glucose | 50931 | 2,711 | mg/dL | mg/dL | [2345-7](https://loinc.org/2345-7) |
| Potassium | 50971 | 3,019 | mEq/L | mmol/L | [2823-3](https://loinc.org/2823-3) |
| Sodium | 50983 | 3,007 | mEq/L | mmol/L | [2951-2](https://loinc.org/2951-2) |

Sodium and potassium are monovalent. Their numeric results and interval bounds carry over unchanged when expressed in `mmol/L`. The source dictionary describes these items as `Blood / Chemistry`. The reviewed crosswalk interprets them as routine serum/plasma measurements for the benchmark. The source cannot establish serum versus plasma for individual observations. `labevent_id` uniquely identifies observations, `subject_id` groups observations for future clustered analyses, and `specimen_id` groups results from the same sample. The reference also retains chart time. [MIMIC lab documentation](https://mimic.mit.edu/docs/iv/modules/hosp/labevents.html) · [UCUM specification](https://ucum.org/ucum)

The [reference lock](../configs/reference-lock.json) records the source checksums, inclusion criteria, units, LOINC codes, and hashes. The SHA-256 of the reference JSON Lines file is `6788d0ad52ed295bcc916d62527b42036dd3f5faa973b4665c2b5b4d62f778f6`. Rows are serialized in observation-ID order with stable field order and UTF-8 encoding. The reader verifies both the cohort and source audit against the lock. Frozen Python records prevent accidental in-memory edits, and the writer accepts an existing snapshot only when its files match byte for byte.

## Scenario A · Unit and value inconsistencies

Sample error rows from glucose and creatinine separately, without replacement. The rate is applied to the eligible nonzero numeric rows for each analyte and rounded down. Split selected rows as evenly as possible across the four subtypes. Sample clean controls separately from remaining rows within each analyte. Correct conversions use glucose ×0.05551 from `mg/dL` to `mmol/L` and creatinine ×88.4 from `mg/dL` to `umol/L`. A change from mass concentration to substance concentration uses the corresponding LOINC property. [CDC conversion factors](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2011/DataFiles/BIOPRO_G.htm) · [Glucose amount code](https://loinc.org/14749-6) · [Creatinine amount code](https://loinc.org/14682-9)

These examples are fabricated and rounded for display. The starting glucose observation is **90 mg/dL**, code **2345-7**, with a displayed interval of **70–100 mg/dL**.

| Output subtype | Value and unit | LOINC | Displayed bounds | Injected error |
|---|---|---|---|---|
| Label only | 90 mmol/L | 2345-7 | 70–100 | Yes |
| Value only | 4.9959 mg/dL | 2345-7 | 70–100 | Yes |
| Stale label | 4.9959 mg/dL | 2345-7 | 3.8857–5.5510 | Yes |
| Wrong factor | 5.4955 mmol/L | 14749-6 | 3.8857–5.5510 | Yes |
| Correct conversion | 4.9959 mmol/L | 14749-6 | 3.8857–5.5510 | No |

For a stale label, both numbers and bounds are converted but the original code and unit remain. The wrong-factor operation applies a 10% excess to the converted value while the code, unit, and bounds use the correct alternate representation. The example wrong-factor value falls inside its displayed interval. For an electrolyte control, a fabricated sodium result of 140 `mmol/L` can be expressed as 140 `mEq/L` with the same LOINC and the same numeric bounds. The same equivalence applies to potassium. Errors and clean conversions are disjoint within a run.

## Scenarios B and C · Mapping errors and omissions

Assign every patient to one of 20 synthetic feed batches by default. Sort patients by a stable hash of their ID, then allocate them round-robin so batches have the same number of patients in this cohort. A patient's repeated observations stay together. Each mapping entry is keyed by **batch and source item ID**. Changing one entry affects all observations with that key. These are simulated batches with uneven row counts.

- **B · Incorrect mappings.** Replace selected entries with another active code, preserving source IDs, values, units, and bounds. In a fabricated example, potassium item 50971 in one batch might receive sodium code `2951-2`, with the same `mmol/L` unit. Specimen substitutions retain the analyte and quantity property. Use urine for glucose and creatinine and whole blood for sodium and potassium. The latter are wrong relative to the benchmark's reviewed serum/plasma mapping assumption. [Urine glucose](https://loinc.org/2350-7) · [Urine creatinine](https://loinc.org/2161-8) · [Whole-blood sodium](https://loinc.org/2947-0) · [Whole-blood potassium](https://loinc.org/6298-4)
- **C · Incomplete mappings.** Remove selected entries and the observations that would fail an integration join on batch and source item ID. In a fabricated example, deleting the potassium mapping for one batch leaves its upstream observation IDs intact and omits those observations from the integrated output. Protect one mapping entry per analyte, selected using the seed, so even the maximum rate retains all four analytes. Apply the rate to the remaining mapping entries and round down. Report both the number of removed entries and the resulting missing observation count.

## Reproduction and input separation

From the repository root after Phase 2 ingestion, run:

```sh
uv run --locked python -m semantic_quality.reference
uv run --locked python -m semantic_quality.corruption A --seed 42 --rate 0.05
uv run --locked python -m semantic_quality.corruption B --seed 42 --rate 0.05
uv run --locked python -m semantic_quality.corruption C --seed 42 --rate 0.05
uv run --locked python -m pytest -q
```

Use `--rate 0` for each scenario's unchanged control. Positive-rate A runs default to `--control-rate 0.05` on rows remaining per analyte. For a conversion-only run, use both `--rate 0` and an explicit positive `--control-rate`. Change `--seed` to change assignments while keeping batch membership fixed. Each invocation starts from the frozen reference and simulates one scenario. Separate runs can select the same observation independently.

The command prints the path to its local run. Hand future validators only the files for their allowed evidence tier.

| Local run path | Contents |
|---|---|
| `validator_input/observations.jsonl` | Integrated observation rows. Use alone for output-only validation. |
| `validator_input/source_aware/upstream_inventory.jsonl` | Identifiers for all eligible observations before mapping, including rows omitted in C. |
| `validator_input/source_aware/feed_mappings.jsonl` | The batch mappings used to integrate the feed. B can contain wrong targets and C can have missing entries. |
| `ground_truth/observation_changes.jsonl` | Changed and omitted observations with original and altered payloads, subtype, batch, seed, and Boolean injected-error status. |
| `ground_truth/mapping_changes.jsonl` | Changed or removed mapping entries with the same scenario context and before/after codes. |
| `ground_truth/run.json` | Private run settings, denominators, counts, and reference fingerprint. |

The observation manifest is sparse. A present entry with `is_error: false` identifies an intentionally changed, valid representation. For scoring, the evaluator can use the upstream observation IDs as the universe and treat IDs absent from the manifest as having no injected change. A removed record has a null altered payload. Both input tiers and the ground truth remain in Git-ignored local storage.

## Verification and Phase 4 handoff

All **24 tests passed**, including 17 Phase 3 tests. Real-data runs for seeds 42 and 13 at a 5% target reproduced byte for byte and produced different error assignments across seeds. The zero-rate validator inputs matched byte for byte across A, B, and C. The raw gzip files, Phase 2 database and aggregate profile, and frozen reference files retained the same hashes through the replay.

| Seed 42, 5% target | Eligible for error sampling | Changed mapping entries | Error-affected observations | Omitted observations |
|---|---:|---:|---:|---:|
| A | 5,714 glucose or creatinine observations | 0 | 285 | 0 |
| B | 80 batch-mapping entries | 4 | 542 | 0 |
| C | 76 removable entries out of 80 | 3 | 259 | 259 |

A also generated 270 correct conversions and 300 equivalent-unit controls. Twenty of the 70 wrong-factor results were within their displayed reference interval. That arithmetic check verifies the presence of errors that can look numerically plausible. It does not establish clinical plausibility, fasting status, or validator performance.

Phase 4 should run structural and semantic checks on exactly the same observations, using separate output-only and source-aware comparisons. A source-aware reconciliation can identify omissions by looking for upstream IDs absent downstream. Terminology verification should use independently specified rules or a trusted registry with declared provenance. Keep the simulation's reference values, private run configuration, and `configs/lab-mappings.csv` out of validator interfaces. That simulation config lists the deliberately wrong candidate codes. Validate units and terminology in the context of each scenario before applying any numeric bounds. Preserve separate observation and mapping denominators.

The error modes and batch composition are synthetic. At the same target mapping rate, different seeds can affect markedly different numbers of observations. The single-hospital cohort contains repeated results from 100 patients, and the source dictionary cannot confirm individual specimen matrices. Shared errors within a batch and repeated measurements within patients matter for later uncertainty estimates. Some correctly labeled wrong-factor values are indistinguishable from genuine values without independent source evidence.
