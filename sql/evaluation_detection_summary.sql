-- A pooled ratio uses total counts, so seeds with different denominators contribute proportionally.
WITH counts AS (
    SELECT
        scenario, target_rate, tier, method, entity, subtype, policy, available,
        any_value(unavailable_reason) AS unavailable_reason,
        count(*) AS runs,
        sum(eligible_count) AS eligible_exposures,
        sum(injected_count) AS injected_exposures,
        sum(tp) AS tp, sum(fp) AS fp, sum(tn) AS tn, sum(fn) AS fn,
        sum(reviewed_count) AS reviewed_count,
        sum(review_only_count) AS review_only_count,
        count(recall) AS recall_defined_runs,
        min(recall) AS recall_seed_min,
        quantile_cont(recall, 0.25) AS recall_seed_q1,
        median(recall) AS recall_seed_median,
        quantile_cont(recall, 0.75) AS recall_seed_q3,
        max(recall) AS recall_seed_max,
        count(precision) AS precision_defined_runs,
        min(precision) AS precision_seed_min,
        quantile_cont(precision, 0.25) AS precision_seed_q1,
        median(precision) AS precision_seed_median,
        quantile_cont(precision, 0.75) AS precision_seed_q3,
        max(precision) AS precision_seed_max,
        count(f1) AS f1_defined_runs,
        min(f1) AS f1_seed_min,
        quantile_cont(f1, 0.25) AS f1_seed_q1,
        median(f1) AS f1_seed_median,
        quantile_cont(f1, 0.75) AS f1_seed_q3,
        max(f1) AS f1_seed_max,
        count(false_positive_rate) AS false_positive_rate_defined_runs,
        min(false_positive_rate) AS false_positive_rate_seed_min,
        quantile_cont(false_positive_rate, 0.25) AS false_positive_rate_seed_q1,
        median(false_positive_rate) AS false_positive_rate_seed_median,
        quantile_cont(false_positive_rate, 0.75) AS false_positive_rate_seed_q3,
        max(false_positive_rate) AS false_positive_rate_seed_max
    FROM detection_runs
    GROUP BY scenario, target_rate, tier, method, entity, subtype, policy, available
)
SELECT *,
    tp / nullif(tp + fp, 0) AS precision,
    tp / nullif(tp + fn, 0) AS recall,
    2 * tp / nullif(2 * tp + fp + fn, 0) AS f1,
    fp / nullif(fp + tn, 0) AS false_positive_rate,
    reviewed_count / nullif(eligible_exposures, 0) AS review_workload_rate
FROM counts
ORDER BY scenario, target_rate, tier, entity, subtype, method, policy;
