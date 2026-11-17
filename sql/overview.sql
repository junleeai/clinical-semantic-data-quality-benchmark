WITH per_patient AS (
    -- Collapse repeated events to one count per patient and analyte.
    SELECT itemid, subject_id, count(*) AS measurements
    FROM selected_labs
    WHERE subject_id IS NOT NULL
    GROUP BY itemid, subject_id
), ranked AS (
    SELECT *, row_number() OVER (PARTITION BY itemid ORDER BY measurements DESC, subject_id) AS rank
    FROM per_patient
), patient_summary AS (
    SELECT
        itemid,
        min(measurements) AS min_per_patient,
        quantile_cont(measurements, 0.25) AS q1_per_patient,
        median(measurements) AS median_per_patient,
        round(avg(measurements), 2) AS mean_per_patient,
        quantile_cont(measurements, 0.75) AS q3_per_patient,
        max(measurements) AS max_per_patient,
        count(*) FILTER (WHERE measurements = 1) AS patients_with_one_measurement,
        round(100.0 * sum(measurements) FILTER (WHERE rank <= 10) / sum(measurements), 2)
            AS pct_measurements_top_10_patients
    FROM ranked
    GROUP BY itemid
)
SELECT
    a.itemid,
    a.analyte,
    d.label AS dictionary_label,
    d.fluid,
    d.category,
    a.expected_source_unit,
    count(l.labevent_id) AS observations,
    count(*) FILTER (WHERE l.valid_numeric) AS valid_numeric_observations,
    count(*) FILTER (WHERE l.valuenum IS NOT NULL AND NOT l.valid_numeric) AS nonfinite_numeric,
    count(DISTINCT l.subject_id) AS patients_with_observations,
    count(DISTINCT l.subject_id) FILTER (WHERE l.valid_numeric) AS patients_with_numeric,
    count(*) FILTER (WHERE l.valid_numeric AND l.unit = a.expected_source_unit)
        AS numeric_with_expected_unit,
    count(DISTINCT p.subject_id) FILTER (WHERE l.valid_numeric AND l.unit = a.expected_source_unit)
        AS patients_numeric_with_expected_unit,
    count(*) FILTER (WHERE l.subject_id IS NOT NULL AND p.subject_id IS NULL)
        AS rows_without_matching_patient,
    s.* EXCLUDE (itemid)
FROM analytes AS a
LEFT JOIN d_labitems AS d USING (itemid)
LEFT JOIN selected_labs AS l USING (itemid)
LEFT JOIN patients AS p ON l.subject_id = p.subject_id
LEFT JOIN patient_summary AS s ON a.itemid = s.itemid
GROUP BY ALL
ORDER BY a.analyte;
