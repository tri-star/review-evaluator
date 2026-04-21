-- Mergeable precision by day
SELECT
  date,
  mergeable.precision AS mergeable_precision
FROM ai_pr_daily_summaries
ORDER BY date DESC;

-- Human-review precision by day
SELECT
  date,
  human_review.precision AS human_review_precision
FROM ai_pr_daily_summaries
ORDER BY date DESC;

-- Missed issues and false positives by day
SELECT
  date,
  missed_issue_count,
  false_positive_count
FROM ai_pr_daily_summaries
ORDER BY date DESC;
