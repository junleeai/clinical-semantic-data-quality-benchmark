# Reproduction and publication audit

## Measured clean replay

The Phase 6 check used an isolated copy of the project inputs and code with a fresh virtual environment, dependency cache, and empty data and results directories. It used Apple Silicon macOS with eight logical CPU cores, 8 GiB of RAM, Python 3.11.14, and DuckDB 1.4.5. Dependency and source acquisition used the network, and acquisition fetched only the three pinned PhysioNet v2.2 tables. The locally installed `uv` orchestrated the commands. The README lists the complete relative-path workflow.

| Step | Observed wall time |
|---|---:|
| Dependency installation | 7.10 s |
| Official acquisition, SHA-256 verification and ingestion | 6.92 s |
| SQL profile | 0.21 s |
| Reference generation and fingerprint verification | 0.28 s |
| Standalone C generation and matching Tier 3 validation check | 0.75 s |
| Full 93-run benchmark and original figures | 163.50 s |
| Independent detection and creatinine audit | 25.54 s |
| Portfolio figures | 1.20 s |
| Test command | 0.89 s |

The measured stages total about **3 minutes and 27 seconds**. The full benchmark step peaked at about **237 MiB of resident memory**. The clean virtual environment occupied about **130 MiB**, excluding dependency caches. The three source files occupied **2.1 MiB**, and the replay's processed-data directory occupied **9.5 MiB**, including the standalone scenario and validation check. Runtime and storage measurements apply to this setup. Other operating systems and CPU architectures were outside the reproduction check. Network availability and installation of `uv` remain prerequisites for a fresh environment.

The clean replay matched the committed aggregate profile, all Phase 5 tables and figures, all Phase 6 audit tables and portfolio figures, and the reference metadata byte for byte. The benchmark independently cross-checked 62 metrics through DuckDB. The Phase 6 audit independently repeated the precision and recall arithmetic and reconstructed the 10-run creatinine finding from row-level local inputs. All **64 tests passed**. [Provenance](../results/phase-5/provenance.json) · [Cross-checks](../results/phase-5/cross_checks.csv) · [Phase 6 audit](results-audit.md)

To exercise generation and validation without the full benchmark, run these commands after ingestion and reference preparation. The generator prints the destination path. The path below is its deterministic output for the supplied parameters.

```sh
uv run --locked python -m semantic_quality.corruption C --seed 42 --rate 0.05
uv run --locked python -m semantic_quality.validation \
  data/processed/scenarios/f45492dc513994e9b0bf/validator_input --tier 3 \
  > data/processed/validation-check.jsonl
```

## Privacy, security, and licensing

- **Data boundary.** Git ignores `data/` and local database or temporary files. That covers raw clinical CSVs, the patient-level DuckDB database, the frozen observations, the source audit, upstream IDs, validation findings, and simulation truth. Only aggregate outputs and fabricated test records belong in the publication tree.
- **History check.** The local publication candidate and reachable Git history were checked for raw tables, DuckDB files, row-level output and ground-truth artifacts. Published aggregate tables contain no patient or observation ID columns. Figures were visualized and checked for patient identifiers. The existing Git history includes the configured author email as commit metadata.
- **Evidence isolation.** Separate directories and explicit file allowlists keep private manifests outside the validation interface. The evaluator reads labels only after methods run on staged inputs. Repository tests verify evidence-tier access and reject symlink escapes. The sources and frozen rule files are checked locally by SHA-256 during reproduction.
- **Third-party terms.** The repository attributes the dataset and provides the versioned inputs and method to regenerate results. The notices identify separate ODbL, LOINC, UCUM, and MIMIC Code terms. The original project code awaits an author-selected license. [Notices](../NOTICES.md)

The local candidate is suitable for review before publication. Publication remains a separate action under the project owner's approval.
