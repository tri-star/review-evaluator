from __future__ import annotations

from datetime import datetime
from collections.abc import Iterable
from typing import Any, Protocol


class GitHubApiClientProtocol(Protocol):
    """Protocol for GitHub API clients used by the review evaluation service."""

    def fetch_pr_labels(self, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Fetch labels for a pull request.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            pr_number: Pull request number such as ``123``.

        Returns:
            A list of label objects such as ``[{"name": "ai-eval:success"}]``.
        """


class ReviewEvaluationService:
    """Evaluate AI review results and build aggregate summaries."""

    def __init__(self, github_api_client: GitHubApiClientProtocol | None) -> None:
        """Initialize the service.

        Args:
            github_api_client: GitHub label lookup client. Pass ``None`` when label lookup is unavailable.

        Returns:
            None. Example: ``ReviewEvaluationService(github_api_client=client)``.
        """
        self.github_api_client = github_api_client

    def evaluate_reviews(
        self,
        reviews: list[dict[str, Any]],
        evaluated_at: str,
    ) -> list[dict[str, Any]]:
        """Evaluate a list of review records against current GitHub labels.

        Args:
            reviews: Review result records such as
                ``[{"repo": "owner/repo", "pr_number": 1, "verdict": "mergeable"}]``.
            evaluated_at: Evaluation timestamp in ISO 8601 format such as
                ``"2026-04-16T06:00:00+00:00"``.

        Returns:
            Evaluated records such as
            ``[{"pr_number": 1, "evaluation_status": "success", "labels": ["ai-eval:success"]}]``.
        """
        return [
            self.evaluate_review(review=review, evaluated_at=evaluated_at)
            for review in reviews
        ]

    def evaluate_review(
        self, review: dict[str, Any], evaluated_at: str
    ) -> dict[str, Any]:
        """Evaluate a single review record using PR labels.

        Args:
            review: Review result record such as
                ``{"repo": "owner/repo", "pr_number": 1, "run_at": "...", "verdict": "mergeable"}``.
            evaluated_at: Evaluation timestamp in ISO 8601 format such as
                ``"2026-04-16T06:00:00+00:00"``.

        Returns:
            An evaluation record such as
            ``{"evaluation_status": "success", "missed_issue": False, "false_positive": False}``.
        """
        labels = self._fetch_label_names(
            repo=review["repo"], pr_number=int(review["pr_number"])
        )
        if "ai-eval:success" in labels:
            evaluation_status = "success"
        elif "ai-eval:failure" in labels:
            evaluation_status = "failure"
        else:
            evaluation_status = "excluded"

        return {
            "repo": review["repo"],
            "pr_number": review["pr_number"],
            "head_sha": review.get("head_sha"),
            "review_run_at": review["run_at"],
            "evaluated_at": evaluated_at,
            "verdict": review["verdict"],
            "evaluation_status": evaluation_status,
            "labels": labels,
            "missed_issue": "ai-review:missed-issue" in labels,
            "false_positive": "ai-review:false-positive" in labels,
        }

    def build_daily_summary(
        self,
        repo: str,
        target_date: str,
        evaluations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build the daily aggregate summary from evaluation records.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            target_date: Summary date string such as ``"2026-04-16"``.
            evaluations: Evaluation records such as
                ``[{"verdict": "mergeable", "evaluation_status": "success"}]``.

        Returns:
            A daily summary such as
            ``{"date": "2026-04-16", "mergeable": {"precision": 1.0}, "excluded_runs": 0}``.
        """
        return {
            "repo": repo,
            "date": target_date,
            **self.summarize_evaluations(evaluations=evaluations),
        }

    def build_weekly_summary(
        self,
        repo: str,
        target_date: str,
        evaluations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build the weekly aggregate summary from the last seven days of evaluations.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            target_date: End date string such as ``"2026-04-20"``.
            evaluations: Evaluation records gathered across one week.

        Returns:
            A weekly summary such as
            ``{"week": "2026-W17", "mergeable": {"precision": 0.75}}``.
        """
        iso_year, iso_week, _ = datetime.fromisoformat(target_date).isocalendar()
        daily = self.build_daily_summary(
            repo=repo, target_date=target_date, evaluations=evaluations
        )
        return {
            "repo": repo,
            "week": f"{iso_year}-W{iso_week:02d}",
            "review_runs": daily["review_runs"],
            "evaluated_runs": daily["evaluated_runs"],
            "excluded_runs": daily["excluded_runs"],
            "mergeable": daily["mergeable"],
            "human_review": daily["human_review"],
            "missed_issue_count": daily["missed_issue_count"],
            "false_positive_count": daily["false_positive_count"],
        }

    def build_period_summary(
        self,
        repo: str,
        label: str,
        evaluations: list[dict[str, Any]],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Build an aggregate summary for a named reporting period.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            label: Human-readable period label such as ``"Last 7 days"``.
            evaluations: Evaluation records gathered across the period.
            start_date: Optional inclusive start date such as ``"2026-04-14"``.
            end_date: Optional inclusive end date such as ``"2026-04-20"``.

        Returns:
            A period summary such as
            ``{"label": "All-time", "mergeable": {"precision": 0.75}}``.
        """
        return {
            "repo": repo,
            "label": label,
            "start_date": start_date,
            "end_date": end_date,
            **self.summarize_evaluations(evaluations=evaluations),
        }

    def build_period_summary_from_daily_summaries(
        self,
        repo: str,
        label: str,
        daily_summaries: list[dict[str, Any]],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Build a named period summary from stored daily summaries.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            label: Human-readable period label such as ``"All-time"``.
            daily_summaries: Daily aggregate summaries loaded from storage.
            start_date: Optional inclusive start date such as ``"2026-04-14"``.
            end_date: Optional inclusive end date such as ``"2026-04-20"``.

        Returns:
            A period summary such as
            ``{"label": "All-time", "mergeable": {"precision": 0.75}}``.
        """
        mergeable = self.summarize_summary_verdicts(
            summary["mergeable"] for summary in daily_summaries
        )
        human_review = self.summarize_summary_verdicts(
            summary["human_review"] for summary in daily_summaries
        )
        return {
            "repo": repo,
            "label": label,
            "start_date": start_date,
            "end_date": end_date,
            "review_runs": sum(summary["review_runs"] for summary in daily_summaries),
            "evaluated_runs": sum(
                summary["evaluated_runs"] for summary in daily_summaries
            ),
            "excluded_runs": sum(
                summary["excluded_runs"] for summary in daily_summaries
            ),
            "mergeable": mergeable,
            "human_review": human_review,
            "missed_issue_count": sum(
                summary["missed_issue_count"] for summary in daily_summaries
            ),
            "false_positive_count": sum(
                summary["false_positive_count"] for summary in daily_summaries
            ),
        }

    def summarize_evaluations(
        self, evaluations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Summarize common metrics from evaluation records."""
        evaluated = [
            item for item in evaluations if item["evaluation_status"] != "excluded"
        ]
        mergeable = [item for item in evaluated if item["verdict"] == "mergeable"]
        human_review = [item for item in evaluated if item["verdict"] == "human-review"]

        return {
            "review_runs": len(evaluations),
            "evaluated_runs": len(evaluated),
            "excluded_runs": len(evaluations) - len(evaluated),
            "mergeable": self.summarize_verdict(mergeable),
            "human_review": self.summarize_verdict(human_review),
            "missed_issue_count": sum(
                1 for item in evaluations if item["missed_issue"]
            ),
            "false_positive_count": sum(
                1 for item in evaluations if item["false_positive"]
            ),
        }

    def summarize_verdict(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Summarize precision metrics for a verdict bucket.

        Args:
            items: Evaluation records filtered by verdict, such as
                ``[{"evaluation_status": "success"}, {"evaluation_status": "failure"}]``.

        Returns:
            A summary dict such as ``{"total": 2, "success": 1, "failure": 1, "precision": 0.5}``.
        """
        success = sum(1 for item in items if item["evaluation_status"] == "success")
        failure = sum(1 for item in items if item["evaluation_status"] == "failure")
        total = len(items)
        precision = success / total if total else 0
        return {
            "total": total,
            "success": success,
            "failure": failure,
            "precision": precision,
        }

    def summarize_summary_verdicts(
        self, verdict_summaries: Iterable[dict[str, Any]]
    ) -> dict[str, Any]:
        """Summarize precision metrics from stored verdict summaries."""
        summaries = list(verdict_summaries)
        success = sum(summary["success"] for summary in summaries)
        failure = sum(summary["failure"] for summary in summaries)
        total = sum(summary["total"] for summary in summaries)
        precision = success / total if total else 0
        return {
            "total": total,
            "success": success,
            "failure": failure,
            "precision": precision,
        }

    def _fetch_label_names(self, repo: str, pr_number: int) -> list[str]:
        """Fetch PR label names using the configured GitHub client.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            pr_number: Pull request number such as ``123``.

        Returns:
            A list of label names such as ``["ai-eval:success", "ai-review:missed-issue"]``.
        """
        if self.github_api_client is None:
            return []
        labels = self.github_api_client.fetch_pr_labels(repo=repo, pr_number=pr_number)
        return [label["name"] for label in labels]
