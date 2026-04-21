-- Replace ${DATABASE_NAME} and ${S3_BUCKET} before execution.
-- Review JSON must be stored as JSON Lines (one object per file line).
-- Raw review objects currently keep repo/pr_number/run_at in the S3 path rather than
-- the JSON body, so the review table exposes only body fields plus Hive partitions.

CREATE EXTERNAL TABLE IF NOT EXISTS `${DATABASE_NAME}`.ai_pr_reviews (
  verdict string,
  confidence double,
  reasons array<string>,
  violated_docs array<string>,
  touched_paths array<string>,
  referenced_paths array<string>,
  author string,
  tool string,
  review_comment_url string
)
PARTITIONED BY (
  repo_partition string,
  year string,
  month string,
  day string
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://${S3_BUCKET}/reviews/';

CREATE EXTERNAL TABLE IF NOT EXISTS `${DATABASE_NAME}`.ai_pr_evaluations (
  repo string,
  pr_number int,
  head_sha string,
  review_run_at string,
  evaluated_at string,
  verdict string,
  evaluation_status string,
  labels array<string>,
  missed_issue boolean,
  false_positive boolean
)
PARTITIONED BY (
  repo_partition string,
  year string,
  month string,
  day string
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://${S3_BUCKET}/evaluations/';

CREATE EXTERNAL TABLE IF NOT EXISTS `${DATABASE_NAME}`.ai_pr_daily_summaries (
  repo string,
  date string,
  review_runs int,
  evaluated_runs int,
  excluded_runs int,
  mergeable struct<total:int,success:int,failure:int,precision:double>,
  human_review struct<total:int,success:int,failure:int,precision:double>,
  missed_issue_count int,
  false_positive_count int
)
PARTITIONED BY (
  repo_partition string,
  date_partition string
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://${S3_BUCKET}/aggregates/daily/';
