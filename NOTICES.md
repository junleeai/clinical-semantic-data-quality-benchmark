# Data and third-party notices

## MIMIC-IV Clinical Database Demo

The reports, figures, and aggregate tables contain information from **MIMIC-IV Clinical Database Demo v2.2**, made available under the **Open Data Commons Open Database License 1.0**. Cite Johnson, A., Bulgarelli, L., Pollard, T., Horng, S., Celi, L. A., and Mark, R. (2023), PhysioNet, RRID:SCR_007345. PhysioNet also requests its platform citation, Pollard et al. (2026), *PhysioNet as a global platform for biomedical research*. [Dataset DOI](https://doi.org/10.13026/dp1f-ex47) · [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) · [Platform DOI](https://doi.org/10.1038/s44360-026-00096-z)

Section 4.3 describes attribution for public use of produced works. Sections 4.4 and 4.6 cover share-alike and access to publicly used derivative databases, including where applicable those behind a produced work. Section 4.6 permits supplying a machine-readable method and the additional contents necessary to reproduce the changes. The repository includes the versioned acquisition links, official hashes, schemas, selection SQL, terminology configuration, simulation code, and run settings. Public materials should retain the dataset and license notice. Source CSVs, patient-level databases, and private manifests stay in local storage. [License terms, section 4](https://opendatacommons.org/licenses/odbl/1-0/#40-conditions-of-use) · [Reproduction instructions](README.md#run-and-reproduce)

## Terminology and methods

> This material contains content from LOINC (http://loinc.org). LOINC is copyright © Regenstrief Institute, Inc. and the Logical Observation Identifiers Names and Codes (LOINC) Committee and is available at no cost under the license at http://loinc.org/license. LOINC® is a registered United States trademark of Regenstrief Institute, Inc.

The curated terminology registry and simulation mapping table use the codes listed in the [LOINC display-name table](#loinc-display-names). [Regenstrief copyright and license](https://loinc.org/license)

UCUM symbols follow the *Unified Code for Units of Measure*. The specification is maintained by Regenstrief Institute and the UCUM Organization. CDC NHANES documentation supplies the glucose and creatinine conversion factors. [UCUM specification](https://ucum.org/ucum) · [UCUM copyright and license](https://ucum.org/license) · [CDC biochemistry documentation](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2011/DataFiles/BIOPRO_G.htm)

The MIT Laboratory for Computational Physiology's crosswalk informed the four source mappings. Its chemistry SQL informed the screening thresholds. MIMIC Code is MIT-licensed, copyright 2019 MIT Laboratory for Computational Physiology. The project references the crosswalk and analytical thresholds and carries its own implementation. [MIMIC Code license](https://github.com/MIT-LCP/mimic-code/blob/main/LICENSE) · [Crosswalk](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/mapping/d_labitems_to_loinc.csv) · [Chemistry SQL](https://github.com/MIT-LCP/mimic-code/blob/main/mimic-iv/concepts/measurement/chemistry.sql)

DuckDB, NumPy, Matplotlib, pytest and their dependencies are installed from package distributions with their own licenses. The project's original code is available under the [MIT License](LICENSE). MIMIC-IV Demo and applicable derivative data remain subject to ODbL. LOINC and UCUM content remain subject to their respective terms.

### LOINC display names

| Code | LOINC long common name |
|---|---|
| [14682-9](https://loinc.org/14682-9) | Creatinine [Moles/volume] in Serum or Plasma |
| [14749-6](https://loinc.org/14749-6) | Glucose [Moles/volume] in Serum or Plasma |
| [2160-0](https://loinc.org/2160-0) | Creatinine [Mass/volume] in Serum or Plasma |
| [2161-8](https://loinc.org/2161-8) | Creatinine [Mass/volume] in Urine |
| [2339-0](https://loinc.org/2339-0) | Glucose [Mass/volume] in Blood |
| [2345-7](https://loinc.org/2345-7) | Glucose [Mass/volume] in Serum or Plasma |
| [2350-7](https://loinc.org/2350-7) | Glucose [Mass/volume] in Urine |
| [2823-3](https://loinc.org/2823-3) | Potassium [Moles/volume] in Serum or Plasma |
| [2947-0](https://loinc.org/2947-0) | Sodium [Moles/volume] in Blood |
| [2951-2](https://loinc.org/2951-2) | Sodium [Moles/volume] in Serum or Plasma |
| [6298-4](https://loinc.org/6298-4) | Potassium [Moles/volume] in Blood |
