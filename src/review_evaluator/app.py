from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

from infrastructures.github_api import GitHubApiClient
from infrastructures.github_summary_publisher import GitHubSummaryPublisher
from infrastructures.s3_review_store import S3ReviewStore
from infrastructures.secrets_manager import SecretsManagerStore
from infrastructures.slack_notifier import SlackNotifier
from services.review_evaluation_service import ReviewEvaluationService
from services.summary_render_service import SummaryRenderService


JST = timezone(timedelta(hours=9))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run the daily review evaluation Lambda flow.

    Args:
        event: Lambda event payload such as ``{}`` from EventBridge.
        context: Lambda context object passed by AWS.

    Returns:
        Execution summary such as
        ``{"date": "2026-04-16", "review_runs": 3, "evaluated_runs": 2, "excluded_runs": 1}``.
    """
    bucket = required_env("REVIEW_DATA_BUCKET")
    repo = required_env("REPO_FULL_NAME")

    now = datetime.now(JST)
    target_date = (now - timedelta(days=1)).date().isoformat()

    review_store = S3ReviewStore(s3_client=boto3.client("s3"), bucket=bucket)
    secret_store = SecretsManagerStore(client=boto3.client("secretsmanager"))

    integrations_secret_arn = os.getenv("INTEGRATIONS_SECRET_ARN")
    github_token = secret_store.read_secret_value(
        arn=integrations_secret_arn, key="github/pat"
    )
    slack_webhook = secret_store.read_secret_value(
        arn=integrations_secret_arn, key="slack/webhook-url"
    )
    github_api_client = GitHubApiClient(token=github_token) if github_token else None
    github_summary_publisher = (
        GitHubSummaryPublisher(token=github_token) if github_token else None
    )
    slack_notifier = SlackNotifier()
    service = ReviewEvaluationService(github_api_client=github_api_client)
    summary_render_service = SummaryRenderService()

    reviews = review_store.load_review_results(repo=repo, target_date=target_date)
    evaluations = service.evaluate_reviews(
        reviews=reviews,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )

    for item in evaluations:
        review_store.write_evaluation(item=item)

    daily_summary = service.build_daily_summary(
        repo=repo, target_date=target_date, evaluations=evaluations
    )
    review_store.write_summary(
        summary=daily_summary, period="daily", key_name=target_date
    )

    weekly_summary = None
    if now.weekday() == 0:
        weekly_evaluations = review_store.load_weekly_evaluations(
            repo=repo, end_date=now.date()
        )
        weekly_summary = service.build_weekly_summary(
            repo=repo,
            target_date=now.date().isoformat(),
            evaluations=weekly_evaluations,
        )
        review_store.write_summary(
            summary=weekly_summary, period="weekly", key_name=weekly_summary["week"]
        )

    if github_summary_publisher and os.getenv("SUMMARY_ISSUE_NUMBER"):
        issue_body = summary_render_service.render_issue_body(
            daily_summary=daily_summary,
            weekly_summary=weekly_summary,
        )
        github_summary_publisher.update_summary_issue(
            repo=repo,
            issue_number=os.environ["SUMMARY_ISSUE_NUMBER"],
            body=issue_body,
        )

    if slack_webhook:
        slack_text = summary_render_service.render_slack_text(
            daily_summary=daily_summary,
            weekly_summary=weekly_summary,
        )
        slack_notifier.post_summary(
            webhook_url=slack_webhook,
            text=slack_text,
        )

    return {
        "date": target_date,
        "review_runs": len(reviews),
        "evaluated_runs": daily_summary["evaluated_runs"],
        "excluded_runs": daily_summary["excluded_runs"],
    }


def required_env(name: str) -> str:
    """Read a required environment variable.

    Args:
        name: Environment variable name such as ``"REVIEW_DATA_BUCKET"``.

    Returns:
        The environment variable value such as ``"ai-pr-review-data"``.
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
