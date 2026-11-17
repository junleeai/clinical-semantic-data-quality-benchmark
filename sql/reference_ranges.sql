SELECT
    itemid,
    unit,
    CASE WHEN isfinite(ref_range_lower) THEN ref_range_lower END AS lower_bound,
    CASE WHEN isfinite(ref_range_upper) THEN ref_range_upper END AS upper_bound,
    CASE
        WHEN ref_range_lower IS NULL AND ref_range_upper IS NULL THEN 'missing both'
        WHEN (ref_range_lower IS NOT NULL AND NOT isfinite(ref_range_lower))
            OR (ref_range_upper IS NOT NULL AND NOT isfinite(ref_range_upper)) THEN 'nonfinite'
        WHEN ref_range_lower IS NULL THEN 'missing lower'
        WHEN ref_range_upper IS NULL THEN 'missing upper'
        WHEN ref_range_lower > ref_range_upper THEN 'reversed'
        ELSE 'complete and ordered'
    END AS range_status,
    count(*) AS observations,
    count(*) FILTER (WHERE valid_numeric) AS valid_numeric_observations
FROM selected_labs
GROUP BY ALL
ORDER BY itemid, observations DESC, unit, lower_bound, upper_bound, range_status;
