# Portfolio summary and technical discussion

## Project summary

Lab records can pass structural checks while carrying the wrong unit or a code for the wrong test. This Python, SQL and DuckDB benchmark compares conventional checks with checks that also examine the meaning of the test, specimen and unit.

The reference contains **11,740 numeric observations from 100 patients** in MIMIC-IV Demo v2.2. Errors and feed batches are simulated. Across **90 nonzero runs**, pooled observation recall was **35.24% for conventional checks and 74.60% for semantic checks** when both had the same trusted registry (Tier 3). This is the error-only policy: review findings are excluded. Counts pool repeated runs of the cohort, not distinct patients.

Quarantine did not always improve the analysis. At the 5% unit-error target, median glucose mean distortion fell from **19.85% to 2.34%**, while creatinine distortion rose from **216.07% to 220.11%**. These are medians across ten seeds at Tier 3. Detecting erroneous records and improving the remaining data are different outcomes.

For project direction, review and implementation attribution, see the [development approach](../README.md#development-approach).

## Proposed GitHub metadata

**Description:** Python, SQL and DuckDB benchmark comparing structural and semantic lab-data checks under simulated unit and mapping errors.

**Topics:** `python`, `sql`, `duckdb`, `healthcare-informatics`, `data-quality`.

These are proposed metadata, not a record of applied repository settings.

## Resume options

These alternatives describe project direction and review with Codex assistance.

| Target role | Suggested bullet |
|---|---|
| Data Analyst / Analytics Engineer | Directed and reviewed a Codex-assisted Python, SQL and DuckDB benchmark on 11,740 lab observations; the analysis showed when removing flagged errors improved glucose summaries and worsened creatinine summaries. |
| Data Engineer | Directed and reviewed a Codex-assisted lab-data benchmark with checksum-verified ingestion, upstream reconciliation and matched inputs for conventional and semantic validation. |
| Data Scientist | Directed and reviewed a Codex-assisted, 93-run simulated data-quality benchmark; pooled observation recall was 35.24% versus 74.60% under a shared registry and error-only scoring. |

## Case study

**Problem.** A wrong code can put a result into the wrong analytical group; a wrong unit label can change how its value is interpreted.

**Comparison.** The pipeline verifies three MIMIC-IV Demo v2.2 tables and freezes the numeric reference. Python injects unit and mapping errors across 90 nonzero runs and three clean controls. SQL builds the cohort and calculates summaries. Both validators receive the same information within each evidence tier. Only the evaluator sees the injected-error labels.

**Results and evidence.** The recall gain under a shared registry was **39.36 percentage points**. Both source-aware methods also identified all **21,306 omitted observation exposures** across 30 omission runs, covering **150 removed mapping entries**. These counts accumulate across runs. Output-only omission recall is undefined because the missing IDs are unavailable. Adding upstream evidence and adding semantic rules are separate changes.

**Why quarantine failed for creatinine.** At the 5% target with seed 42, the clean mean was **1.542 mg/dL**, the integrated mean **5.021 mg/dL**, and the mean after semantic quarantine **5.085 mg/dL**. The 38 removed rows were correctly flagged label-only errors. Their interpreted values were low, while larger upward errors remained. A separate DuckDB calculation reproduced the mechanism and matched all ten seeds at this target.

**Scope.** Distortion means the absolute percentage difference from the clean reference mean. This simulated benchmark does not establish performance in production or across other hospitals.

## Technical discussion guide

These notes explain the implementation and results.

1. **How are the source tables joined?** Lab events carry a source `itemid` and patient `subject_id`. The item joins the lab dictionary and the subject joins the patient table. `labevent_id` stays the observation key, so repeat tests do not collapse into one event.
2. **How does an anti-join find missing observations?** It compares upstream observation IDs with the integrated output and returns IDs with no match. An output-only validator cannot know those identities. Both source-aware methods use the same reconciliation.
3. **What do semantic checks add?** Structural checks cover required fields, types, unique IDs, finite values, broad ranges and referential integrity. A valid registry code can still identify the wrong test. Semantic rules compare the meaning of the source item with the meaning of its target code.
4. **Why can two LOINC codes describe glucose?** Codes can differ in the measured quantity or specimen. Serum/plasma glucose expressed as mass per volume uses a different code from glucose expressed as substance amount per volume. The source dictionary's broad blood label leaves some specimen distinctions uncertain.
5. **How are units normalized?** The implementation uses analyte-specific factors. Creatinine in `umol/L` is divided by 88.4 for `mg/dL`. Sodium and potassium are monovalent, so `mEq/L` and `mmol/L` have a one-to-one numerical relationship. The downstream consumer trusts the delivered unit, allowing the benchmark to measure the effect of incorrect metadata.
6. **What makes the comparison fair?** Both methods see identical corrupted records and identical evidence within a tier. Rules and the registry version stay fixed. Only the evaluator joins findings to the injected-error labels. The Tier 3 difference therefore measures the added semantic rules under matched evidence.
7. **What do precision and recall mean here?** Recall is the fraction of injected errors detected. Precision is the fraction of flagged entities with injected errors. Conventional precision in A and B is undefined because that method raises no positives. Review-inclusive scoring counts review findings under a separate policy.
8. **Why resample patients instead of rows?** Measurements from one patient can be related. Resampling whole patients within fixed batches keeps those observations together. Using the same draw for both methods makes the comparison paired.
9. **How do bootstrap intervals differ from seed ranges?** The bootstrap varies the patient composition while holding the batch design and error assignment fixed. Different seeds change where the simulated errors occur. They answer different uncertainty questions.
10. **How was the creatinine increase checked?** A separate SQL calculation recomputed conversions, means and error-subtype contributions. At the 5% seed-42 anchor, quarantine removed 38 low values while leaving large upward errors. Pinned data and rules, explicit seeds and a recorded byte-for-byte replay make the result inspectable.

[README](../README.md) · [Technical report](technical-report.md) · [Results audit](results-audit.md) · [Reproduction record](reproducibility.md)
