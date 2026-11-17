# Phase 2 dataset profile

Aggregate counts derived from **MIMIC-IV Clinical Database Demo v2.2**, Johnson et al. (2023), PhysioNet, ODbL 1.0. The project README provides attribution and reproduction instructions. [Dataset release](https://doi.org/10.13026/dp1f-ex47) · [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)

## Coverage and units

All three compressed files matched the published SHA-256 hashes. Ingestion loaded 107,727 lab events, 1,622 dictionary items, and 100 patients. All four selected dictionary entries have the listed analyte as their exact label, fluid `Blood`, and category `Chemistry`. Every selected observation joins to a patient. All 100 patients have at least one finite result with the observed unit for each analyte. [Official checksums](https://physionet.org/content/mimic-iv-demo/2.2/SHA256SUMS.txt)

| Analyte (item ID) | Total | Valid numeric | Distinct patients | Observed unit and frequency |
|---|---:|---:|---:|---|
| Glucose (50931) | 2,711 | 2,711 | 100 | mg/dL · 2,711 (100%) |
| Creatinine (50912) | 3,003 | 3,003 | 100 | mg/dL · 3,003 (100%) |
| Sodium (50983) | 3,007 | 3,007 | 100 | mEq/L · 3,007 (100%) |
| Potassium (50971) | 3,022 | 3,019 | 100 | mEq/L · 3,022 (100%) |

Valid numeric means the source `valuenum` is present and finite. This definition does not include a clinical plausibility threshold. Units are profiled as source strings with surrounding whitespace trimmed. The totals include all matching lab events, including rows with a missing admission ID. MIMIC's lab documentation notes that admission links can be absent. [Lab events documentation](https://mimic.mit.edu/docs/iv/modules/hosp/labevents.html)

| Analyte | Mean measurements per patient | Median | Middle 50% | Min–max | Share from 10 most measured patients |
|---|---:|---:|---:|---:|---:|
| Glucose | 27.11 | 12 | 6.75–26.5 | 2–216 | 45.41% |
| Creatinine | 30.03 | 14.5 | 7–28.25 | 2–233 | 45.75% |
| Sodium | 30.07 | 15 | 8–28 | 2–227 | 44.43% |
| Potassium | 30.22 | 15 | 8–28 | 2–236 | 44.67% |

These counts use all observations for each patient. Fractional quartiles are interpolated between patient counts. The top-ten share is computed independently for each analyte.

## Missing fields and reference intervals

Each percentage uses all observations for that analyte as its denominator. Blank strings and SQL nulls count as missing. The masked display value `___` is profiled separately.

| Field | Glucose | Creatinine | Sodium | Potassium |
|---|---:|---:|---:|---:|
| Numeric result | 0 | 0 | 0 | 3 (0.10%) |
| Display value | 0 | 0 | 0 | 3 (0.10%) |
| Unit | 0 | 0 | 0 | 0 |
| Lower or upper reference bound | 0 | 0 | 0 | 0 |
| Admission ID | 407 (15.01%) | 637 (21.21%) | 558 (18.56%) | 561 (18.56%) |
| Ordering provider ID | 2,529 (93.29%) | 2,599 (86.55%) | 2,674 (88.93%) | 2,686 (88.88%) |
| Result flag | 643 (23.72%) | 1,726 (57.48%) | 2,351 (78.18%) | 2,708 (89.61%) |
| Comments | 0 | 2,963 (98.67%) | 2,511 (83.51%) | 2,766 (91.53%) |

All remaining profiled columns had zero missing values. All 2,711 glucose display values were masked, as were 40 creatinine, 496 sodium, and 253 potassium display values. Each masked row still had a finite numeric result. Use `valuenum` as the numeric input. Treat blank flags as missing flag metadata when profiling.

| Analyte | Source interval and count |
|---|---|
| Glucose | 70–100 mg/dL (2,711) |
| Creatinine | 0.5–1.2 mg/dL (1,687), 0.4–1.1 mg/dL (1,316) |
| Sodium | 133–145 mEq/L (2,501), 135–147 mEq/L (506) |
| Potassium | 3.3–5.1 mEq/L (2,755), 3.5–5.4 mEq/L (267) |

All 11,743 observations had finite, ordered reference bounds, including the three potassium rows without numeric results. These are source-reported intervals. Glucose comments in the public preview qualify the range by fasting status, which the tabular schema does not provide as a structured field. Keep abnormal-result summaries secondary and define their context before use. [Lab events preview](https://physionet.org/content/mimic-iv-demo/2.2/hosp/labevents.csv.gz)

## LOINC mapping review

The checksum-verified v2.2 dictionary has no native LOINC field. The review started with the confirmed v2.2 labels, fluid, category, and observed units, then checked the proposed terms on Regenstrief's official pages. Each is active and defines a quantitative point-in-time measurement with no specified method. The local label establishes the component. The observed unit supports the concentration property. As a separate check, MIT-LCP's chemistry extraction uses these same four IDs and excludes blood gases and point-of-care tests. The existing v2.0 crosswalk supports the serum/plasma system consistently with this routine chemistry context. [MIT-LCP chemistry extraction](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/measurement/chemistry.sql) · [MIT-LCP crosswalk](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/mapping/d_labitems_to_loinc.csv)

| Source ID | Candidate | Verified terminology and compatibility |
|---|---|---|
| 50931 | [2345-7](https://loinc.org/2345-7) | Glucose, mass concentration in serum/plasma, compatible with mg/dL |
| 50912 | [2160-0](https://loinc.org/2160-0) | Creatinine, mass concentration in serum/plasma, compatible with mg/dL |
| 50983 | [2951-2](https://loinc.org/2951-2) | Sodium, substance concentration in serum/plasma. For Na⁺, mEq/L and mmol/L are numerically equivalent |
| 50971 | [2823-3](https://loinc.org/2823-3) | Potassium, substance concentration in serum/plasma. For K⁺, mEq/L and mmol/L are numerically equivalent |

An earlier research table uses `6777-7` for glucose. Regenstrief marks it as a deprecated duplicate and directs users to `2345-7`. This confirms the current choice independently of the v2.0 crosswalk. The exact serum/plasma system remains an item-level assumption for all four mappings. The v2.2 source describes the fluid as `Blood` and supplies a specimen grouping ID. It cannot independently confirm the matrix on a given event. For the benchmark, document these as reviewed analytical mappings and limit specimen checks to what the item-level evidence supports. [Earlier research table](https://openreview.net/pdf?id=Pi9oVd3JqR) · [Regenstrief retirement and replacement](https://loinc.org/6777-7) · [Specimen ID documentation](https://mimic.mit.edu/docs/iv/modules/hosp/labevents.html)

## Feasibility and Phase 3 recommendation

**Keep all four analytes.** The 11,740 finite measurements support a controlled benchmark, including multiple observational corruption rates. A 1% rate gives about 27–30 affected observations per analyte before splitting into subtypes. Report sparse cases separately as counts and avoid relying on precise subtype estimates at the lowest rate. The four source codes provide only four global mapping keys, so a whole-key omission can remove an entire analyte. Use simulated interface batches for graded mapping failures and report both affected keys and affected rows. Each analyte has a single observed source unit, so valid alternate units and unit drift must be represented through controlled simulation.

The same **100 patients** contribute to every analyte. Precision depends on how errors and measurement values cluster within patients and simulated batches. Repeated results from frequently tested patients can dominate a row-weighted summary. In evaluation, resample whole patients jointly across comparison arms, keep seed-to-seed variation separate, and include a patient-weighted sensitivity analysis. Treat uncertainty estimates as conditional on the demo cohort and simulation design. The demo comes from one institution and a restricted sampling frame. It supports a descriptive comparison of controlled defects. Power for small effects, rare subtypes, and cross-site generalization remains unestablished. [Demo sampling methods](https://physionet.org/content/mimic-iv-demo/2.2/#methods)

For Phase 3, freeze an immutable reference keyed by `labevent_id`, use the 11,740 finite numbers with compatible units as the candidate numeric cohort, and keep the three nonnumeric potassium rows visible in the source audit. Define the intended treatment of reference intervals and duplicate or repeated sample measurements before injecting errors. Then specify the seeded scenarios, eligible denominators, clean controls, and separate ground-truth manifest.
