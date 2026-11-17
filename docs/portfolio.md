# Portfolio and interview materials

## GitHub repository description

A reproducible Python and DuckDB benchmark of lab-data validation that measures how simulated unit and mapping errors affect healthcare analytics.

## Resume bullets

| Target role | Bullet |
|---|---|
| Data Analyst / Analytics Engineer | Built a DuckDB and Python benchmark on 11,740 lab observations, using SQL to quantify when semantic quarantine reduced glucose mean distortion from 19.85% to 2.34% and when it increased creatinine distortion. |
| Data Engineer | Designed a checksum-verified MIMIC-IV ETL and validation pipeline with frozen references, isolated error manifests, and upstream reconciliation that identified 21,306 simulated omitted observation exposures across 30 runs. |
| Data Scientist | Designed a 93-run controlled data-quality experiment with paired patient-cluster bootstraps. Semantic rules increased pooled Tier 3 error-only recall from 35.24% to 74.60% under matched evidence. |

## Case study

**Problem.** A clinical results feed can pass schema checks while carrying values in the wrong units or codes for the wrong test. Downstream analysts may interpret those values as trustworthy and report a biased mean or an incomplete cohort.

**Method and build.** I acquired three MIMIC-IV Demo v2.2 tables, verified the official checksums, and froze 11,740 numeric results across four lab tests. SQL built the cohort and generated aggregate summaries. Python simulated unit and mapping defects across 90 perturbed runs and three clean controls. Both validators received identical data within each evidence tier. Labels went only to the evaluator, which separated mapping keys from affected rows and resampled whole patients to estimate uncertainty.

**Results.** With a shared trusted registry, error-only recall rose by 39.36 percentage points. Both methods detected all tested omissions when they had the upstream inventory. This showed that the availability of evidence can matter as much as the choice of validation rules.

**Failure and implication.** Quarantine improved the glucose mean but made the creatinine mean worse. It removed label-only creatinine errors that pulled the mean downward and left larger upward errors behind. I reproduced that mechanism with an independent DuckDB calculation. The result motivates checking how quarantine changes the surviving errors and cohort, even when every removed record was correctly flagged.

## Ten interview questions and answers

1. **How did you join the source tables?** Lab events carry a source `itemid` and patient `subject_id`. The item joins the lab dictionary and the subject joins the patient table. `labevent_id` stays the observation key, so repeat tests do not get collapsed into one event.
2. **How does an anti-join find missing observations?** It compares upstream observation IDs to the integrated output and returns upstream IDs with no match. An output-only validator cannot know those identities. Both source-aware arms used the same reconciliation.
3. **Which checks would you run in a standard quality framework?** Required fields, types, unique IDs, finite values, broad ranges, and referential integrity are useful conventional checks. A valid registry code can still name the wrong analyte. A terminology-aware rule compares the meaning of the source item with the meaning of the target.
4. **Why can two LOINC codes describe glucose?** Codes can differ in quantity property or specimen system. For example, serum/plasma glucose reported as mass per volume uses a different code from serum/plasma glucose reported as substance amount per volume. The source dictionary's broad blood label leaves some specimen distinctions uncertain.
5. **How did you normalize units?** I used analyte-specific factors. Creatinine in `umol/L` is divided by 88.4 for `mg/dL`. Sodium and potassium have a one-to-one numerical relationship between `mEq/L` and `mmol/L` because they are monovalent. The analytics consumer interprets the delivered unit to measure the impact of trusting bad metadata.
6. **What made the comparison fair?** Each pair saw identical corrupted records and identical evidence within a tier. Fixed rules and a registry version were used throughout. The evaluator alone joined findings to the ground truth. The difference at Tier 3 measures the added semantic rules under matched evidence.
7. **What is the difference between precision and recall here?** Recall asks what fraction of injected errors were detected. Precision asks what fraction of flags were injected errors. Conventional precision in A and B is undefined because it raised no positives. Review-inclusive scoring intentionally counts uncertainty flags in a separate policy.
8. **Why resample patients instead of rows?** Measurements from one patient can be related, and a few frequently tested patients contribute many rows. Resampling whole patients keeps those relationships intact. Using the same draw across arms makes the contrast paired.
9. **How do bootstrap intervals differ from seed ranges?** The conditional bootstrap holds the error assignment and batch design fixed while varying which patients are represented in the draw. Different seeds relocate the simulated errors. Both matter, but the intervals and seed ranges answer different questions.
10. **How did you investigate the surprising result and make it reproducible?** I recomputed creatinine conversions, means, and subtype contributions with independent SQL. At the anchor, quarantine removed 38 low values and kept the large inflating errors. A pre-scoring protocol commit, pinned data and rules, explicit seeds, and byte-for-byte replay make the result inspectable.

[Technical report](technical-report.md) · [Results audit](results-audit.md) · [Reproduction record](reproducibility.md)
