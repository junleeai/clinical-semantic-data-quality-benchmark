# Phase 5 benchmark results

The [evaluation protocol](evaluation-protocol.md) and [run configuration](../configs/evaluation-v1.json) were committed before scoring in `bfec339`. The benchmark used the verified MIMIC-IV Clinical Database Demo v2.2 reference and unchanged Phase 3 generator and Phase 4 rules. All three zero-rate controls produced identical inputs and empty findings. The **93 scenario runs** comprise 90 perturbed runs and three controls. Each run used both methods at all three evidence tiers, for **558 method–tier evaluations**. [Run and hash provenance](../results/phase-5/provenance.json)

## Detection

Recall is the share of injected errors found. Precision is the share of flagged records that were injected errors. The false-positive rate is the share of clean records flagged. F1 penalizes a low value of either precision or recall. A metric has no value when its denominator is zero. The tables pool counts across runs in the stated group. The same 100 patients appear repeatedly in those counts.

| Tier 3 observation results, all nonzero settings | TP | FP | TN | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Conventional, errors only | 21,306 | 0 | 996,148 | 39,146 | 100% | 35.24% | 52.12% |
| Semantic, errors only | 45,099 | 0 | 996,148 | 15,353 | 100% | 74.60% | 85.45% |
| Semantic, including reviews | 51,733 | 0 | 996,148 | 8,719 | 100% | 85.58% | 92.23% |

The conventional review-inclusive row is identical to its error-only row. The observed false-positive rate was 0% under both policies in the scored cells. The semantic review-inclusive policy added 6,634 unique review-only observation exposures (881 in A and 5,753 in B). These findings would require review in an operating workflow. In A and B the conventional method produced no positive predictions, so its scenario-level precision is undefined. Its pooled precision is defined because Scenario C contributed true positives. [Per-seed confusion counts and workload](../results/phase-5/detection.csv) · [Pooled scenario and tier summaries](../results/phase-5/detection_summary.csv)

| Scenario and tier | Conventional observation recall | Semantic error-only recall | Semantic review-inclusive recall |
|---|---:|---:|---:|
| A · Tiers 1 and 2 | 0% | 0% | 0% |
| A · Tier 3 | 0% | 25.18% | 32.04% |
| B · Tiers 1 and 2 | 0% | 0% | 0% |
| B · Tier 3 | 0% | 78.14% | 100% |
| C · Tier 1 | Unavailable | Unavailable | Unavailable |
| C · Tiers 2 and 3 | 100% | 100% | 100% |

**Mapping entries.** These are scored separately from observations. In B, Tier 3 semantic validation identified 143 of 180 corrupted batch–item entries as errors. The other 37 were review-only. Conventional validation at Tiers 2 and 3 found none of these wrong but structurally valid entries. In C, both methods found all 150 removed mapping entries and all 21,306 omitted observations with upstream evidence. Tier 1 could not identify individual omitted IDs or score mapping entries. A injects observation changes only.

### Failure analysis

- **Unit labels and factors.** Tier 3 semantic validation flagged all 3,230 label-only errors. Their codes specify mass concentration while their new units express substance concentration. Value-only and stale-label errors left the code and unit compatible. Only values that crossed the registry's broad analyte-specific screen received review. Neither method flagged any of the 3,170 wrong-factor errors, including 1,073 whose values fell inside the displayed interval. An independent same-event original value would be needed to check the arithmetic. The validators flagged none of the 7,900 correct-conversion controls or 9,000 equivalent-unit controls.
- **Incorrect concepts and specimens.** A code can exist in the registry and still describe the wrong analyte. Tier 3 semantic rules flagged all same-unit analyte swaps. They flagged blood-to-urine conflicts as errors and treated whole-blood substitutions as review findings. The `Blood` source label leaves the exact matrix unresolved. Review-inclusive scoring reached 100% recall in B under these injections, while error-only recall varied from 61.5% to 100% across seeds at the 5% target.
- **Omissions.** The upstream anti-join used by both methods explains the complete detection of C. A perfectly identified absence still leaves no measurement to analyze. The quarantine stage removed zero additional observations in C. [Omission accounting by analyte and arm](../results/phase-5/omissions.csv)

At the 5% target, A affected 285 rows per run out of 5,714 error-eligible glucose and creatinine rows. B changed four of 80 mappings and affected 373–949 observations per run. C removed three of 76 removable mappings (80 total) and omitted 259–701 observations per run. Unequal batch sizes give the same mapping-entry rate different effects on observation coverage. [Configured and realized rates](../results/phase-5/runs.csv) · [Detection figure](../results/phase-5/figures/tier3_detection.png)

## Downstream effects and quarantine

The consumer groups values by the delivered analyte code and converts the reported unit to canonical units. A mapping swap can therefore change both analytes' aggregates. Quarantine removes error-flagged observations or observations under an error-flagged mapping key. It cannot correct the value or add an omitted record. The following table shows the median across seeds of absolute mean distortion relative to the clean mean at the 5% target and Tier 3. The exact mean, median, signed and absolute changes, and source-attributed retention are in the impact tables.

| Scenario | Analyte | Integrated | Conventional quarantine | Semantic quarantine |
|---|---|---:|---:|---:|
| A | Creatinine | 216.07% | 216.07% | 220.11% |
| A | Glucose | 19.85% | 19.85% | 2.34% |
| A | Potassium | 0% | 0% | 0% |
| A | Sodium | 0% | 0% | 0% |
| B | Creatinine | 1.53% | 1.53% | 1.54% |
| B | Glucose | 4.50% | 4.50% | 0.34% |
| B | Potassium | 70.06% | 70.06% | 0% |
| B | Sodium | 0.145% | 0.145% | 0.017% |
| C | Creatinine | 1.16% | 1.16% | 1.16% |
| C | Glucose | 0.41% | 0.41% | 0.41% |
| C | Potassium | 0.019% | 0.019% | 0.019% |
| C | Sodium | 0% | 0% | 0% |

In A, a `umol/L`-sized creatinine number labeled `mg/dL` inflates the mean. The label-only error goes in the opposite direction: the unchanged `mg/dL` number is interpreted as the much smaller `umol/L` quantity. Error-only quarantine caught the latter and left the major inflating errors in place. The remaining rows therefore had a more distorted mean, despite correct detection of the removed records. The creatinine median's relative distortion was 10% both before and after quarantine. With one mean per patient, the corresponding cross-seed median creatinine summary still rose from 3.991 to 4.057 mg/dL (clean 1.301 mg/dL), so unequal testing frequency alone does not explain the result.

In B, the tested quarantine helped glucose, potassium, and sodium means at the 5% target, while also reducing available observations and sometimes patient coverage. For glucose, the median count of patients with any eligible result fell from 100 before quarantine to 95 after semantic quarantine. In C at the 15% target, median source observation retention ranged from 83.4% for glucose to 88.1% for creatinine. The median patient count with a result ranged from 82.5 to 87.5 across the four analytes. Fractional medians arise from averaging the two middle seed-level counts. Both validators left the same measurements available.

Across the evaluated runs, zero clean observations were incorrectly quarantined under the primary policy. This does not remove selection bias: quarantining genuine errors can change which patients and measurements contribute to estimates. In Tier 3 across all nonzero settings, semantic quarantine retained 9,600 of 12,830 injected A observations and 5,753 of 26,316 injected B observations, versus all such observations for conventional quarantine. No injected C observation was present initially. [Run-level impact, retention, and quarantine](../results/phase-5/impact.csv) · [Across-seed impact summary](../results/phase-5/impact_summary.csv) · [Distortion figure](../results/phase-5/figures/mean_distortion.png) · [Coverage figure](../results/phase-5/figures/omission_retention.png)

## Uncertainty and interpretation

A paired bootstrap draws whole patients with replacement inside each fixed feed batch. Each draw uses the same patients for the reference and both methods, keeping repeated measurements together. At the 5% target and anchor seed 42, the Tier 3 error-only semantic-minus-conventional recall difference was **+25.3 percentage points** in A (95% conditional bootstrap interval **+20.4 to +28.6**) and **+68.5 points** in B (**+48.3 to +80.8**). It was zero in C under both methods' identical reconciliation. Precision contrasts in A and B were undefined for the anchor because the conventional arm made no positive predictions. The mapping outcomes use seed distributions rather than patient bootstrap intervals.

For the same anchor in A, semantic-minus-conventional absolute mean distortion was **−26.0 mg/dL** for glucose (95% interval **−41.0 to −10.3**) and **+0.064 mg/dL** for creatinine (**+0.039 to +0.096**). These intervals reflect patient resampling with that assignment fixed. Variation across seeds is reported separately, and degenerate intervals such as the zero C contrast do not establish absence of uncertainty in other batches, sites, or corruption designs. [Detection intervals](../results/phase-5/detection_intervals.csv) · [Impact intervals](../results/phase-5/impact_intervals.csv)

The value of the semantic rules here depends on the failure mode. Registry maintenance is justified for identifying contradictions in units and analyte names within this narrow chemistry scope. Upstream inventory is the critical evidence for omissions. Correct arithmetic and fine specimen distinctions need evidence these feeds lack. The study applies simulated errors to one hospital's 100-patient demo and a curated terminology subset. The frozen clean data already fit the rules and support a synthetic specificity check. These results cannot estimate field false-positive rates or clinical effectiveness.

## Reproduction and verification

From the repository root, use the locked Python environment and the Phase 3 reference. The evaluation command stages only validator inputs and then interprets labels in the evaluator. NumPy resamples patient weights, DuckDB aggregates counts across seeds and cross-checks the Python calculations, and Matplotlib renders the figures. Patient-level inputs and labels remain local.

```sh
uv sync --locked
uv run --locked python -m semantic_quality.reference
uv run --locked python -m semantic_quality.evaluation
uv run --locked python -m pytest -q
```

The evaluator and supporting modules are [evaluation.py](../src/semantic_quality/evaluation.py), [detection.py](../src/semantic_quality/detection.py), [analytical_impact.py](../src/semantic_quality/analytical_impact.py), [cluster_bootstrap.py](../src/semantic_quality/cluster_bootstrap.py), and [evaluation_reporting.py](../src/semantic_quality/evaluation_reporting.py). The [detection SQL](../sql/evaluation_detection_summary.sql) and [impact SQL](../sql/evaluation_impact_summary.sql) create the summary tables. The Python environment adds pinned NumPy and Matplotlib versions in [pyproject.toml](../pyproject.toml) and [uv.lock](../uv.lock).

All **64 tests passed**, including 17 new Phase 5 tests. The benchmark ran 62 independent DuckDB checks of confusion counts, mapping true positives, and canonical value statistics. A full replay reproduced every table and figure byte for byte. The input data, reference, validation lock, and registry hashes were unchanged. [Tests](../tests/test_phase5.py) · [Independent cross-checks](../results/phase-5/cross_checks.csv)

For Phase 6, lead with the paired findings: terminology checks caught valid-looking but contradictory codes, reconciliation caught omissions equally well in both arms, and one selective quarantine policy worsened creatinine mean bias. Retain the protocol and replay commands, explain uncertainty and undefined precision in the public README, and use only verified results in the portfolio summary.
