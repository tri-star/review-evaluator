from __future__ import annotations

from typing import Any

from services.review_command_service import ReviewCommandService


class FakeGitHubClient:
    def __init__(self, permission: str = "write") -> None:
        self.permission = permission
        self.calls: list[tuple[Any, ...]] = []

    def fetch_repository_installation(self, repo: str) -> dict[str, Any]:
        self.calls.append(("fetch_repository_installation", repo))
        return {"id": 42}

    def fetch_collaborator_permission(
        self, repo: str, username: str, installation_id: int
    ) -> str:
        self.calls.append(
            ("fetch_collaborator_permission", repo, username, installation_id)
        )
        return self.permission

    def fetch_pull_request(
        self, repo: str, pr_number: int, installation_id: int
    ) -> dict[str, Any]:
        self.calls.append(("fetch_pull_request", repo, pr_number, installation_id))
        return {
            "title": "Add feature",
            "user": {"login": "alice"},
            "head": {
                "sha": "head123",
                "ref": "feature/review",
                "repo": {"full_name": "fork/repo"},
            },
            "base": {"sha": "base456", "ref": "main"},
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


def test_non_created_action_is_ignored_without_github_api_calls() -> None:
    client = FakeGitHubClient()
    service = ReviewCommandService(github_client=client, bot_name="review-bot")

    result = service.handle(_payload(body="@review-bot /review", action="edited"))

    assert result == {"ignored": True, "reason": "unsupported_action"}
    assert client.calls == []


def test_non_pr_issue_comment_is_ignored_without_github_api_calls() -> None:
    client = FakeGitHubClient()
    service = ReviewCommandService(github_client=client, bot_name="review-bot")
    payload = _payload(body="@review-bot /review")
    payload["issue"].pop("pull_request")

    result = service.handle(payload)

    assert result == {"ignored": True, "reason": "not_pull_request"}
    assert client.calls == []


def test_command_mismatch_is_ignored_without_github_api_calls() -> None:
    client = FakeGitHubClient()
    service = ReviewCommandService(github_client=client, bot_name="review-bot")

    result = service.handle(_payload(body="@review-bot help"))

    assert result == {"ignored": True, "reason": "command_mismatch"}
    assert client.calls == []


def test_review_command_matches_with_or_without_slash_case_insensitively() -> None:
    service = ReviewCommandService(
        github_client=FakeGitHubClient(), bot_name="review-bot"
    )

    assert service._matches_review_command("@review-bot /review")
    assert service._matches_review_command("@REVIEW-bot review")


def test_insufficient_permission_posts_warning_and_does_not_dispatch() -> None:
    client = FakeGitHubClient(permission="read")
    service = ReviewCommandService(github_client=client, bot_name="review-bot")

    result = service.handle(_payload(body="@review-bot /review"))

    assert result == {"ignored": True, "reason": "insufficient_permission"}
    assert ("dispatch_review_workflow",) not in client.calls
    assert client.calls[-1][0] == "post_issue_comment"
    assert "権限がありません" in client.calls[-1][3]


def test_sufficient_permission_dispatches_workflow_then_posts_start_comment() -> None:
    client = FakeGitHubClient(permission="maintain")
    service = ReviewCommandService(github_client=client, bot_name="review-bot")

    result = service.handle(_payload(body="@review-bot review"))

    assert result == {"ignored": False, "dispatched": True}
    dispatch_call = client.calls[-2]
    assert dispatch_call == (
        "dispatch_review_workflow",
        "owner/repo",
        "main",
        {
            "pr_number": "123",
            "head_sha": "head123",
            "base_sha": "base456",
            "head_ref": "feature/review",
            "base_ref": "main",
            "head_repo": "fork/repo",
            "pr_title": "Add feature",
            "pr_author": "alice",
        },
        42,
    )
    assert client.calls[-1][0] == "post_issue_comment"
    assert "AI review を開始しました" in client.calls[-1][3]


def _payload(body: str, action: str = "created") -> dict[str, Any]:
    return {
        "action": action,
        "repository": {"full_name": "owner/repo"},
        "issue": {"number": 123, "pull_request": {"url": "https://example.com/pr"}},
        "comment": {"body": body, "user": {"login": "bob"}},
    }
