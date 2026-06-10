from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from infrastructures.github_app_client import GitHubApiError, GitHubAppClient
from infrastructures.github_api import GitHubApiClient
from infrastructures.github_summary_publisher import GitHubSummaryPublisher
from infrastructures.s3_review_store import S3ReviewStore
from infrastructures.secrets_manager import SecretsManagerStore
from infrastructures.slack_notifier import SlackNotifier
from services.review_command_service import ReviewCommandService
from services.review_evaluation_service import ReviewEvaluationService
from services.summary_render_service import SummaryRenderService


JST = timezone(timedelta(hours=9))


def handle_review_command(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle GitHub App issue_comment webhooks for manual review commands."""
    import boto3

    secret_store = SecretsManagerStore(client=boto3.client("secretsmanager"))
    return _handle_review_command(
        event=event,
        secret_store=secret_store,
        client_factory=GitHubAppClient,
    )


def _handle_review_command(
    *,
    event: dict[str, Any],
    secret_store: SecretsManagerStore,
    client_factory: type[GitHubAppClient],
) -> dict[str, Any]:
    integrations_secret_arn = os.getenv("INTEGRATIONS_SECRET_ARN")
    webhook_secret = secret_store.read_secret_value(
        arn=integrations_secret_arn, key="github/webhook-secret"
    )
    if not webhook_secret:
        raise RuntimeError("Missing github/webhook-secret in integrations secret")

    body = _event_body_bytes(event)
    if not _verify_github_signature(
        body=body,
        signature=_header_value(event, "X-Hub-Signature-256"),
        secret=webhook_secret,
    ):
        return _http_response(401, {"message": "invalid signature"})

    payload = json.loads(body.decode("utf-8"))
    app_id = secret_store.read_secret_value(
        arn=integrations_secret_arn, key="github/app-id"
    )
    private_key = secret_store.read_secret_value(
        arn=integrations_secret_arn, key="github/app-private-key"
    )
    if not app_id or not private_key:
        raise RuntimeError("Missing GitHub App credentials in integrations secret")

    bot_name = os.getenv("BOT_NAME", "review-bot")
    github_client = client_factory(app_id=app_id, private_key=private_key)
    service = ReviewCommandService(github_client=github_client, bot_name=bot_name)

    try:
        result = service.handle(payload)
    except GitHubApiError as error:
        return _http_response(error.status, {"message": "GitHub API request failed"})

    return _http_response(200, result)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run the daily review evaluation Lambda flow.

    Args:
        event: Lambda event payload such as ``{}`` from EventBridge.
        context: Lambda context object passed by AWS.

    Returns:
        Execution summary such as
        ``{"date": "2026-04-16", "review_runs": 3, "evaluated_runs": 2, "excluded_runs": 1}``.
    """
    import boto3

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

    recent_end_date = now.date()
    recent_start_date = recent_end_date - timedelta(days=6)
    recent_evaluations = review_store.load_recent_evaluations(
        repo=repo, end_date=recent_end_date, days=7
    )
    recent_summary = service.build_period_summary(
        repo=repo,
        label="Last 7 days",
        start_date=recent_start_date.isoformat(),
        end_date=recent_end_date.isoformat(),
        evaluations=recent_evaluations,
    )
    all_time_summary = service.build_period_summary_from_daily_summaries(
        repo=repo,
        label="All-time",
        daily_summaries=review_store.load_all_daily_summaries(repo=repo),
    )
    if now.weekday() == 0:
        weekly_summary = service.build_weekly_summary(
            repo=repo,
            target_date=recent_end_date.isoformat(),
            evaluations=recent_evaluations,
        )
        review_store.write_summary(
            summary=weekly_summary, period="weekly", key_name=weekly_summary["week"]
        )

    if github_summary_publisher and os.getenv("SUMMARY_ISSUE_NUMBER"):
        issue_body = summary_render_service.render_issue_body(
            daily_summary=daily_summary,
            recent_summary=recent_summary,
            all_time_summary=all_time_summary,
        )
        github_summary_publisher.update_summary_issue(
            repo=repo,
            issue_number=os.environ["SUMMARY_ISSUE_NUMBER"],
            body=issue_body,
        )

    if slack_webhook:
        slack_text = summary_render_service.render_slack_text(
            daily_summary=daily_summary,
            recent_summary=recent_summary,
            all_time_summary=all_time_summary,
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


def _event_body_bytes(event: dict[str, Any]) -> bytes:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return str(body).encode("utf-8")


def _verify_github_signature(
    *, body: bytes, signature: str | None, secret: str
) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, f"sha256={expected}")


def _header_value(event: dict[str, Any], name: str) -> str | None:
    headers = event.get("headers") or {}
    name_lower = name.lower()
    for key, value in headers.items():
        if str(key).lower() == name_lower:
            return str(value)
    return None


def _http_response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, ensure_ascii=False),
    }
