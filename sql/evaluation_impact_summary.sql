-- Corruption seeds vary the location and number of impacted rows.
SELECT
    scenario, target_rate, tier, stage, analyte, canonical_unit,
    count(*) AS runs,
    count(mean_relative_distortion) AS mean_relative_distortion_defined_runs,
    median(mean) AS median_across_seeds_mean,
    median(median) AS median_across_seeds_median,
    median(patient_weighted_mean) AS median_across_seeds_patient_weighted_mean,
    min(mean_difference) AS mean_difference_seed_min,
    quantile_cont(mean_difference, 0.25) AS mean_difference_seed_q1,
    median(mean_difference) AS mean_difference_seed_median,
    quantile_cont(mean_difference, 0.75) AS mean_difference_seed_q3,
    max(mean_difference) AS mean_difference_seed_max,
    min(mean_relative_distortion) AS mean_relative_distortion_seed_min,
    quantile_cont(mean_relative_distortion, 0.25) AS mean_relative_distortion_seed_q1,
    median(mean_relative_distortion) AS mean_relative_distortion_seed_median,
    quantile_cont(mean_relative_distortion, 0.75) AS mean_relative_distortion_seed_q3,
    max(mean_relative_distortion) AS mean_relative_distortion_seed_max,
    median(median_relative_distortion) AS median_relative_distortion_seed_median,
    min(observations) AS observation_count_seed_min,
    median(observations) AS observation_count_seed_median,
    max(observations) AS observation_count_seed_max,
    min(patients) AS patient_count_seed_min,
    median(patients) AS patient_count_seed_median,
    max(patients) AS patient_count_seed_max,
    median(coded_observation_ratio) AS coded_observation_ratio_seed_median,
    median(source_analyte_retention) AS source_analyte_retention_seed_median,
    sum(source_absent_at_integration) AS total_absent_exposures,
    sum(source_quarantined) AS total_quarantined_exposures,
    sum(clean_quarantined) AS total_clean_quarantined_exposures,
    sum(clean_integrated) AS total_clean_integrated_exposures,
    sum(corrupted_retained) AS total_corrupted_retained_exposures,
    sum(injected_observations) AS total_injected_exposures,
    sum(corrupted_integrated) AS total_corrupted_integrated_exposures,
    total_clean_quarantined_exposures / nullif(total_clean_integrated_exposures, 0)
        AS pooled_clean_quarantined_rate,
    total_corrupted_retained_exposures / nullif(total_injected_exposures, 0)
        AS pooled_corrupted_retained_rate,
    total_corrupted_retained_exposures / nullif(total_corrupted_integrated_exposures, 0)
        AS pooled_corrupted_retained_among_present_rate
FROM impact_runs
GROUP BY scenario, target_rate, tier, stage, analyte, canonical_unit
ORDER BY scenario, target_rate, tier, analyte, stage;
