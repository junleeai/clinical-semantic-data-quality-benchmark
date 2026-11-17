-- Keep every matching source event, including those routed to the local source audit.
SELECT
    l.*,
    d.label AS dictionary_label,
    d.fluid,
    d.category,
    p.subject_id IS NOT NULL AS patient_exists,
    coalesce(isfinite(l.valuenum), false) AS finite_numeric
FROM labevents AS l
JOIN selected_items AS i USING (itemid)
LEFT JOIN d_labitems AS d USING (itemid)
LEFT JOIN patients AS p ON l.subject_id = p.subject_id
ORDER BY l.labevent_id;
