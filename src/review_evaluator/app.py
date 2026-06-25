from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from infrastructures.anthropic_rule_generator import AnthropicRuleGenerator
from infrastructures.openai_rule_generator import OpenAIRuleGenerator
from infrastructures.github_app_client import GitHubApiError, GitHubAppClient
from infrastructures.github_api import GitHubApiClient
from infrastructures.github_summary_publisher import GitHubSummaryPublisher
from infrastructures.s3_review_store import S3ReviewStore
from infrastructures.s3_rule_store import S3RuleStore
from infrastructures.secrets_manager import SecretsManagerStore
from infrastructures.slack_notifier import SlackNotifier
from observability import logger
from services.review_command_service import ReviewCommandService
from services.review_evaluation_service import ReviewEvaluationService
from services.rule_extraction_service import RuleExtractionService
from services.rule_retention import (
    DEFAULT_MAX_RULE_COUNT,
    DEFAULT_RETENTION_DAYS,
    select_prunable_rules,
)
from services.summary_render_service import SummaryRenderService


JST = timezone(timedelta(hours=9))


@logger.inject_lambda_context(clear_state=True)
def handle_review_command(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle GitHub App webhooks (issue_comment commands and pull_request events).

    A GitHub App has a single webhook URL, so issue_comment and pull_request
    events both arrive here; routing is by the ``X-GitHub-Event`` header.
    """
    import boto3

    secret_store = SecretsManagerStore(client=boto3.client("secretsmanager"))

    def enqueue(message: dict[str, Any]) -> None:
        sqs = boto3.client("sqs")
        sqs.send_message(
            QueueUrl=required_env("RULE_EXTRACTION_QUEUE_URL"),
            MessageBody=json.dumps(message),
        )

    return _handle_github_webhook(
        event=event,
        secret_store=secret_store,
        client_factory=GitHubAppClient,
        enqueue=enqueue,
    )


def _handle_github_webhook(
    *,
    event: dict[str, Any],
    secret_store: SecretsManagerStore,
    client_factory: type[GitHubAppClient],
    enqueue: Any,
) -> dict[str, Any]:
    """Route a GitHub webhook by ``X-GitHub-Event`` to the matching handler.

    ``pull_request`` closed events enqueue an async rule-extraction job and
    return immediately so the webhook does not time out on LLM work. Everything
    else falls through to the synchronous review-command flow.
    """
    event_type = _header_value(event, "X-GitHub-Event")
    if event_type == "pull_request":
        return _handle_pull_request_event(
            event=event, secret_store=secret_store, enqueue=enqueue
        )
    return _handle_review_command(
        event=event,
        secret_store=secret_store,
        client_factory=client_factory,
    )


def _handle_pull_request_event(
    *,
    event: dict[str, Any],
    secret_store: SecretsManagerStore,
    enqueue: Any,
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
        logger.warning("pull_request webhook: invalid signature")
        return _http_response(401, {"message": "invalid signature"})

    payload = json.loads(body.decode("utf-8"))
    action = payload.get("action")
    if action != "closed":
        logger.info("pull_request webhook ignored", extra={"action": action})
        return _http_response(200, {"ignored": True, "reason": "unsupported_action"})

    repo = (payload.get("repository") or {}).get("full_name")
    pr_number = (payload.get("pull_request") or {}).get("number")
    if not repo or pr_number is None:
        logger.warning("pull_request webhook missing repo or pr_number")
        return _http_response(200, {"ignored": True, "reason": "incomplete_payload"})

    enqueue({"repo": repo, "pr_number": int(pr_number)})
    logger.info(
        "rule extraction enqueued", extra={"repo": repo, "pr_number": pr_number}
    )
    return _http_response(202, {"enqueued": True, "repo": repo, "pr_number": pr_number})


def _build_rule_generator(
    *, secret_store: SecretsManagerStore, arn: str | None
) -> AnthropicRuleGenerator | OpenAIRuleGenerator:
    """Build the rule generator selected by ``RULE_GENERATOR_PROVIDER``.

    Args:
        secret_store: Secrets Manager wrapper used to read the provider API key.
        arn: Integrations secret ARN holding the provider API keys.

    Returns:
        An ``OpenAIRuleGenerator`` or ``AnthropicRuleGenerator``.
    """
    provider = (os.getenv("RULE_GENERATOR_PROVIDER") or "openai").lower()
    if provider == "openai":
        api_key = secret_store.read_secret_value(arn=arn, key="openai/api-key")
        if not api_key:
            raise RuntimeError("Missing openai/api-key in integrations secret")
        return OpenAIRuleGenerator(api_key=api_key)
    if provider == "anthropic":
        api_key = secret_store.read_secret_value(arn=arn, key="anthropic/api-key")
        if not api_key:
            raise RuntimeError("Missing anthropic/api-key in integrations secret")
        return AnthropicRuleGenerator(api_key=api_key)
    raise RuntimeError(f"Unknown RULE_GENERATOR_PROVIDER: {provider}")


@logger.inject_lambda_context(clear_state=True)
def process_rule_extraction(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Worker for SQS-delivered rule-extraction jobs from closed pull requests."""
    import boto3

    bucket = required_env("REVIEW_DATA_BUCKET")
    secret_store = SecretsManagerStore(client=boto3.client("secretsmanager"))
    integrations_secret_arn = os.getenv("INTEGRATIONS_SECRET_ARN")
    app_id = secret_store.read_secret_value(
        arn=integrations_secret_arn, key="github/app-id"
    )
    private_key = secret_store.read_secret_value(
        arn=integrations_secret_arn, key="github/app-private-key"
    )
    if not app_id or not private_key:
        raise RuntimeError("Missing GitHub App credentials in integrations secret")

    service = RuleExtractionService(
        github_client=GitHubAppClient(app_id=app_id, private_key=private_key),
        rule_store=S3RuleStore(s3_client=boto3.client("s3"), bucket=bucket),
        rule_generator=_build_rule_generator(
            secret_store=secret_store, arn=integrations_secret_arn
        ),
    )

    records = event.get("Records", [])
    for record in records:
        body = json.loads(record["body"])
        service.handle(repo=body["repo"], pr_number=int(body["pr_number"]))
    logger.info("rule extraction batch complete", extra={"records": len(records)})
    return {"processed": len(records)}


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
        logger.warning("review command webhook: invalid signature")
        return _http_response(401, {"message": "invalid signature"})

    payload = json.loads(body.decode("utf-8"))
    logger.info(
        "review command webhook received",
        extra={
            "action": payload.get("action"),
            "repo": (payload.get("repository") or {}).get("full_name"),
        },
    )
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


@logger.inject_lambda_context(clear_state=True)
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

    logger.append_keys(repo=repo, target_date=target_date)
    logger.info(
        "daily evaluation started", extra={"bucket": bucket, "weekday": now.weekday()}
    )

    try:
        review_store = S3ReviewStore(s3_client=boto3.client("s3"), bucket=bucket)
        secret_store = SecretsManagerStore(client=boto3.client("secretsmanager"))

        integrations_secret_arn = os.getenv("INTEGRATIONS_SECRET_ARN")
        github_token = secret_store.read_secret_value(
            arn=integrations_secret_arn, key="github/pat"
        )
        slack_webhook = secret_store.read_secret_value(
            arn=integrations_secret_arn, key="slack/webhook-url"
        )
        summary_issue_number = os.getenv("SUMMARY_ISSUE_NUMBER")
        logger.info(
            "configuration resolved",
            extra={
                "github_token_present": bool(github_token),
                "slack_webhook_present": bool(slack_webhook),
                "summary_issue_configured": bool(summary_issue_number),
                "integrations_secret_configured": bool(integrations_secret_arn),
            },
        )

        github_api_client = (
            GitHubApiClient(token=github_token) if github_token else None
        )
        github_summary_publisher = (
            GitHubSummaryPublisher(token=github_token) if github_token else None
        )
        slack_notifier = SlackNotifier()
        service = ReviewEvaluationService(github_api_client=github_api_client)
        summary_render_service = SummaryRenderService()

        reviews = review_store.load_review_results(repo=repo, target_date=target_date)
        logger.info("reviews loaded", extra={"count": len(reviews)})

        evaluations = service.evaluate_reviews(
            reviews=reviews,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )
        status_counts = {
            "success": sum(
                1 for e in evaluations if e["evaluation_status"] == "success"
            ),
            "failure": sum(
                1 for e in evaluations if e["evaluation_status"] == "failure"
            ),
            "excluded": sum(
                1 for e in evaluations if e["evaluation_status"] == "excluded"
            ),
        }
        logger.info(
            "evaluations complete", extra={"count": len(evaluations), **status_counts}
        )

        for item in evaluations:
            review_store.write_evaluation(item=item)
        logger.info("evaluations written", extra={"count": len(evaluations)})

        daily_summary = service.build_daily_summary(
            repo=repo, target_date=target_date, evaluations=evaluations
        )
        review_store.write_summary(
            summary=daily_summary, period="daily", key_name=target_date
        )
        logger.info(
            "daily summary written",
            extra={
                "review_runs": daily_summary["review_runs"],
                "evaluated_runs": daily_summary["evaluated_runs"],
                "excluded_runs": daily_summary["excluded_runs"],
            },
        )

        recent_end_date = now.date()
        recent_start_date = recent_end_date - timedelta(days=6)
        recent_evaluations = review_store.load_recent_evaluations(
            repo=repo, end_date=recent_end_date, days=7
        )
        logger.info(
            "recent evaluations loaded", extra={"count": len(recent_evaluations)}
        )

        recent_summary = service.build_period_summary(
            repo=repo,
            label="Last 7 days",
            start_date=recent_start_date.isoformat(),
            end_date=recent_end_date.isoformat(),
            evaluations=recent_evaluations,
        )
        all_daily_summaries = review_store.load_all_daily_summaries(repo=repo)
        all_time_summary = service.build_period_summary_from_daily_summaries(
            repo=repo,
            label="All-time",
            daily_summaries=all_daily_summaries,
        )
        logger.info(
            "all-time summary built",
            extra={"daily_summary_count": len(all_daily_summaries)},
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
            logger.info(
                "weekly summary written", extra={"week": weekly_summary["week"]}
            )
        else:
            logger.info("weekly summary skipped", extra={"weekday": now.weekday()})

        if github_summary_publisher and summary_issue_number:
            issue_body = summary_render_service.render_issue_body(
                daily_summary=daily_summary,
                recent_summary=recent_summary,
                all_time_summary=all_time_summary,
            )
            github_summary_publisher.update_summary_issue(
                repo=repo,
                issue_number=summary_issue_number,
                body=issue_body,
            )
        else:
            logger.info(
                "GitHub summary issue update skipped",
                extra={
                    "reason": "no_token"
                    if not github_summary_publisher
                    else "no_issue_number",
                },
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
        else:
            logger.info(
                "Slack notification skipped", extra={"reason": "no_webhook_url"}
            )

        pruned_rules = _prune_low_usage_rules(
            rule_store=S3RuleStore(s3_client=boto3.client("s3"), bucket=bucket),
            now=datetime.now(timezone.utc),
        )

        result = {
            "date": target_date,
            "review_runs": len(reviews),
            "evaluated_runs": daily_summary["evaluated_runs"],
            "excluded_runs": daily_summary["excluded_runs"],
            "pruned_rules": pruned_rules,
        }
        logger.info("daily evaluation completed", extra=result)
        return result
    except Exception:
        logger.exception("daily evaluation failed")
        raise


def _prune_low_usage_rules(*, rule_store: S3RuleStore, now: datetime) -> int:
    """Delete low-usage rules when the rule set has grown too large.

    Args:
        rule_store: Rule store to read from and delete within.
        now: Current time as an aware datetime.

    Returns:
        The number of rules deleted.
    """
    retention_days = int(os.getenv("RULE_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)))
    max_count = int(os.getenv("RULE_MAX_COUNT", str(DEFAULT_MAX_RULE_COUNT)))
    rule_ids = select_prunable_rules(
        rule_store.list_rules(),
        now=now,
        retention_days=retention_days,
        max_count=max_count,
    )
    for rule_id in rule_ids:
        rule_store.delete_rule(rule_id)
    if rule_ids:
        logger.info("low-usage rules pruned", extra={"count": len(rule_ids)})
    return len(rule_ids)


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
