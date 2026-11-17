SELECT
    itemid,
    unit,
    count(*) AS observations,
    count(*) FILTER (WHERE valid_numeric) AS valid_numeric_observations,
    round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY itemid), 2) AS pct_observations
FROM selected_labs
GROUP BY itemid, unit
ORDER BY itemid, observations DESC, unit;
