from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import app
from infrastructures.github_app_client import GitHubApiError


class FakeSecretStore:
    def __init__(self) -> None:
        self.values = {
            "github/webhook-secret": "webhook-secret",
            "github/app-id": "123456",
            "github/app-private-key": "private-key",
        }

    def read_secret_value(self, arn: str | None, key: str) -> str | None:
        return self.values.get(key)


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, app_id: str, private_key: str) -> None:
        self.app_id = app_id
        self.private_key = private_key
        self.calls: list[tuple[Any, ...]] = []
        FakeClient.instances.append(self)

    def fetch_repository_installation(self, repo: str) -> dict[str, Any]:
        self.calls.append(("fetch_repository_installation", repo))
        return {"id": 99}

    def fetch_collaborator_permission(
        self, repo: str, username: str, installation_id: int
    ) -> str:
        self.calls.append(
            ("fetch_collaborator_permission", repo, username, installation_id)
        )
        return "write"

    def fetch_pull_request(
        self, repo: str, pr_number: int, installation_id: int
    ) -> dict[str, Any]:
        self.calls.append(("fetch_pull_request", repo, pr_number, installation_id))
        return {
            "title": "PR title",
            "user": {"login": "alice"},
            "head": {
                "sha": "head-sha",
                "ref": "feature",
                "repo": {"full_name": "owner/repo"},
            },
            "base": {"sha": "base-sha", "ref": "main"},
        }

    def fetch_repository(self, repo: str, installation_id: int) -> dict[str, Any]:
        self.calls.append(("fetch_repository", repo, installation_id))
        return {"default_branch": "main"}

    def dispatch_review_workflow(
        self, repo: str, ref: str, inputs: dict[str, str], installation_id: int
    ) -> None:
        self.calls.append(
            ("dispatch_review_workflow", repo, ref, inputs, installation_id)
        )

    def post_issue_comment(
        self, repo: str, issue_number: int, body: str, installation_id: int
    ) -> None:
        self.calls.append(
            ("post_issue_comment", repo, issue_number, body, installation_id)
        )


class FailingClient(FakeClient):
    def fetch_repository_installation(self, repo: str) -> dict[str, Any]:
        raise GitHubApiError(status=502, message="secret private-key leaked")


def test_valid_signature_accepts_request(monkeypatch: Any) -> None:
    FakeClient.instances = []
    monkeypatch.setenv("INTEGRATIONS_SECRET_ARN", "arn")
    monkeypatch.setenv("BOT_NAME", "review-bot")
    response = app._handle_review_command(
        event=_event(_payload("@review-bot /review")),
        secret_store=FakeSecretStore(),
        client_factory=FakeClient,
    )

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"ignored": False, "dispatched": True}
    assert FakeClient.instances[0].app_id == "123456"


def test_invalid_signature_returns_401(monkeypatch: Any) -> None:
    FakeClient.instances = []
    monkeypatch.setenv("INTEGRATIONS_SECRET_ARN", "arn")
    event = _event(_payload("@review-bot /review"))
    event["headers"]["X-Hub-Signature-256"] = "sha256=bad"

    response = app._handle_review_command(
        event=event,
        secret_store=FakeSecretStore(),
        client_factory=FakeClient,
    )

    assert response["statusCode"] == 401
    assert FakeClient.instances == []


def test_missing_signature_returns_401(monkeypatch: Any) -> None:
    FakeClient.instances = []
    monkeypatch.setenv("INTEGRATIONS_SECRET_ARN", "arn")
    event = _event(_payload("@review-bot /review"))
    event["headers"] = {}

    response = app._handle_review_command(
        event=event,
        secret_store=FakeSecretStore(),
        client_factory=FakeClient,
    )

    assert response["statusCode"] == 401
    assert FakeClient.instances == []


def test_github_api_failure_returns_sanitized_error(monkeypatch: Any) -> None:
    monkeypatch.setenv("INTEGRATIONS_SECRET_ARN", "arn")
    monkeypatch.setenv("BOT_NAME", "review-bot")

    response = app._handle_review_command(
        event=_event(_payload("@review-bot /review")),
        secret_store=FakeSecretStore(),
        client_factory=FailingClient,
    )

    assert response["statusCode"] == 502
    assert "private-key" not in response["body"]
    assert "webhook-secret" not in response["body"]


def _payload(body: str) -> dict[str, Any]:
    return {
        "action": "created",
        "repository": {"full_name": "owner/repo"},
        "issue": {"number": 123, "pull_request": {"url": "https://example.com/pr"}},
        "comment": {"body": body, "user": {"login": "bob"}},
    }


def _event(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload)
    digest = hmac.new(
        b"webhook-secret",
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "headers": {"X-Hub-Signature-256": f"sha256={digest}"},
        "body": body,
        "isBase64Encoded": False,
    }
