-- Each row contributes a true/false flag to every field or special-value count.
SELECT
    itemid,
    field,
    count(*) FILTER (WHERE missing) AS missing_observations,
    count(*) AS observations,
    round(100.0 * count(*) FILTER (WHERE missing) / count(*), 2) AS pct_missing
FROM selected_labs
CROSS JOIN LATERAL (
    VALUES
        ('labevent_id', labevent_id IS NULL),
        ('subject_id', subject_id IS NULL),
        ('hadm_id', hadm_id IS NULL),
        ('specimen_id', specimen_id IS NULL),
        ('itemid', itemid IS NULL),
        ('order_provider_id', nullif(trim(order_provider_id), '') IS NULL),
        ('charttime', charttime IS NULL),
        ('storetime', storetime IS NULL),
        ('value', nullif(trim(value), '') IS NULL),
        ('valuenum', valuenum IS NULL),
        ('valueuom', unit IS NULL),
        ('ref_range_lower', ref_range_lower IS NULL),
        ('ref_range_upper', ref_range_upper IS NULL),
        ('flag', nullif(trim(flag), '') IS NULL),
        ('priority', nullif(trim(priority), '') IS NULL),
        ('comments', nullif(trim(comments), '') IS NULL)
) AS fields (field, missing)
GROUP BY itemid, field
ORDER BY itemid, field;
