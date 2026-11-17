SELECT
    itemid,
    count(*) FILTER (WHERE trim(value) = '___') AS masked_display_values,
    count(*) FILTER (WHERE trim(value) = '___' AND valid_numeric)
        AS masked_display_values_with_valid_numeric
FROM selected_labs
GROUP BY itemid
ORDER BY itemid;
