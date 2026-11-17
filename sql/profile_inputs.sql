-- Restrict the profile to the configured item IDs while keeping all matching rows.
CREATE TEMP VIEW selected_labs AS
SELECT
    l.*,
    coalesce(isfinite(l.valuenum), false) AS valid_numeric,
    nullif(trim(l.valueuom), '') AS unit
FROM labevents AS l
JOIN analytes AS a USING (itemid);
