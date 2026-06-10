from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any


REVIEW_KEY_PATTERN = re.compile(
    r"^reviews/repo_partition=(?P<repo_partition>[^/]+)/year=(?P<year>\d{4})/"
    r"month=(?P<month>\d{2})/day=(?P<day>\d{2})/pr=(?P<pr_number>\d+)/"
    r"run=(?P<run_at>[^/]+)\.json$"
)


class S3ReviewStore:
    """S3-backed store for review, evaluation, and summary JSON files."""

    def __init__(self, s3_client: Any, bucket: str) -> None:
        """Initialize the S3 store.

        Args:
            s3_client: Boto3 S3 client instance.
            bucket: Bucket name such as ``"ai-pr-review-data"``.

        Returns:
            None. Example: ``S3ReviewStore(s3_client=s3, bucket="ai-pr-review-data")``.
        """
        self.s3_client = s3_client
        self.bucket = bucket

    def load_review_results(self, repo: str, target_date: str) -> list[dict[str, Any]]:
        """Load review result JSON files for a single day from S3.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            target_date: Target date string such as ``"2026-04-16"``.

        Returns:
            A list of review result dicts such as
            ``[{"repo": "owner/repo", "pr_number": 1, "verdict": "mergeable"}]``.
        """
        year, month, day = target_date.split("-")
        prefix = f"reviews/repo_partition={repo.replace('/', '_')}/year={year}/month={month}/day={day}/"
        items = self._load_json_objects(prefix=prefix)
        return [self._normalize_review_item(item=item) for item in items]

    def load_weekly_evaluations(
        self, repo: str, end_date: date
    ) -> list[dict[str, Any]]:
        """Load evaluation JSON files for the last seven days from S3.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            end_date: End date such as ``date(2026, 4, 20)``.

        Returns:
            A list of evaluation dicts across one week.
        """
        return self.load_recent_evaluations(repo=repo, end_date=end_date, days=7)

    def load_recent_evaluations(
        self, repo: str, end_date: date, days: int
    ) -> list[dict[str, Any]]:
        """Load evaluation JSON files for a rolling date window from S3.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            end_date: Inclusive end date such as ``date(2026, 4, 20)``.
            days: Number of days to load, including the end date.

        Returns:
            A list of evaluation dicts across the requested date window.
        """
        if days < 1:
            raise ValueError("days must be greater than or equal to 1")

        repo_key = repo.replace("/", "_")
        evaluations: list[dict[str, Any]] = []
        for offset in range(days):
            target = end_date - timedelta(days=offset)
            year = target.strftime("%Y")
            month = target.strftime("%m")
            day = target.strftime("%d")
            prefix = f"evaluations/repo_partition={repo_key}/year={year}/month={month}/day={day}/"
            evaluations.extend(self._load_json_objects(prefix=prefix))
        return evaluations

    def load_all_daily_summaries(self, repo: str) -> list[dict[str, Any]]:
        """Load all daily summary JSON files for a repository from S3.

        Args:
            repo: Repository full name such as ``"owner/repo"``.

        Returns:
            A list of all daily summary dicts under the repository partition.
        """
        repo_key = repo.replace("/", "_")
        prefix = f"aggregates/daily/repo_partition={repo_key}/"
        return self._load_json_objects(prefix=prefix)

    def write_evaluation(self, item: dict[str, Any]) -> None:
        """Write a single evaluation result to S3.

        Args:
            item: Evaluation record such as
                ``{"repo": "owner/repo", "pr_number": 1, "evaluated_at": "2026-04-16T06:00:00+00:00"}``.

        Returns:
            None. The JSON file is written to the `evaluations/` prefix.
        """
        evaluated_at = datetime.fromisoformat(
            item["evaluated_at"].replace("Z", "+00:00")
        )
        year = evaluated_at.strftime("%Y")
        month = evaluated_at.strftime("%m")
        day = evaluated_at.strftime("%d")
        repo_key = item["repo"].replace("/", "_")
        key = (
            f"evaluations/repo_partition={repo_key}/year={year}/month={month}/day={day}/"
            f"pr={item['pr_number']}.json"
        )
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(item).encode("utf-8"),
            ContentType="application/json",
        )

    def write_summary(
        self, summary: dict[str, Any], period: str, key_name: str
    ) -> None:
        """Write a daily or weekly summary JSON file to S3.

        Args:
            summary: Summary dict such as ``{"repo": "owner/repo", "date": "2026-04-16"}``.
            period: Summary period string, either ``"daily"`` or ``"weekly"``.
            key_name: Partition key string such as ``"2026-04-16"`` or ``"2026-W17"``.

        Returns:
            None. The JSON file is written to the `aggregates/` prefix.
        """
        repo_key = summary["repo"].replace("/", "_")
        if period == "daily":
            key = f"aggregates/daily/repo_partition={repo_key}/date={key_name}/summary.json"
        else:
            key = f"aggregates/weekly/repo_partition={repo_key}/week={key_name}/summary.json"
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(summary).encode("utf-8"),
            ContentType="application/json",
        )

    def _load_json_objects(self, prefix: str) -> list[dict[str, Any]]:
        """Load JSON files from an S3 prefix.

        Args:
            prefix: S3 key prefix such as ``"reviews/repo=owner_repo/year=2026/month=04/day=16/"``.

        Returns:
            A list of JSON objects loaded from all files under the prefix.
        """
        paginator = self.s3_client.get_paginator("list_objects_v2")
        items: list[dict[str, Any]] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for content in page.get("Contents", []):
                key = content["Key"]
                body = (
                    self.s3_client.get_object(Bucket=self.bucket, Key=key)["Body"]
                    .read()
                    .decode("utf-8")
                )
                for line in body.splitlines():
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    payload["s3_key"] = key
                    items.append(payload)
        return items

    def _normalize_review_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Fill missing review fields from the S3 object key.

        Args:
            item: Raw review payload loaded from S3, including ``s3_key`` metadata.

        Returns:
            A normalized review payload with repo, pr_number, and run_at populated.
        """
        normalized = dict(item)
        key = normalized.pop("s3_key", "")
        match = REVIEW_KEY_PATTERN.match(key)
        if match is None:
            return normalized

        normalized.setdefault(
            "repo", match.group("repo_partition").replace("_", "/", 1)
        )
        normalized.setdefault("pr_number", int(match.group("pr_number")))
        run_at = match.group("run_at").replace("Z", "+00:00")
        if len(run_at) >= 19 and run_at[13] == "-" and run_at[16] == "-":
            run_at = run_at[:13] + ":" + run_at[14:16] + ":" + run_at[17:]
        normalized.setdefault("run_at", run_at)
        return normalized
