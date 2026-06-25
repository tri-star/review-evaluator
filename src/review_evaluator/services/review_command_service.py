from __future__ import annotations

import re
from typing import Any, Protocol

from observability import logger


ALLOWED_PERMISSIONS = {"write", "maintain", "admin"}
WORKFLOW_FILE = "pr-ai-review.yml"


class ReviewCommandGitHubClient(Protocol):
    def fetch_repository_installation(self, repo: str) -> dict[str, Any]: ...

    def fetch_collaborator_permission(
        self, repo: str, username: str, installation_id: int
    ) -> str: ...

    def fetch_pull_request(
        self, repo: str, pr_number: int, installation_id: int
    ) -> dict[str, Any]: ...

    def fetch_repository(self, repo: str, installation_id: int) -> dict[str, Any]: ...

    def dispatch_review_workflow(
        self, repo: str, ref: str, inputs: dict[str, str], installation_id: int
    ) -> None: ...

    def post_issue_comment(
        self, repo: str, issue_number: int, body: str, installation_id: int
    ) -> None: ...


class ReviewCommandService:
    """Handle GitHub issue comment review commands."""

    def __init__(self, github_client: ReviewCommandGitHubClient, bot_name: str) -> None:
        self.github_client = github_client
        self.bot_name = bot_name.lstrip("@")

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action")
        if action != "created":
            logger.info(
                "review command ignored",
                extra={"reason": "unsupported_action", "action": action},
            )
            return {"ignored": True, "reason": "unsupported_action"}

        issue = payload.get("issue") or {}
        if "pull_request" not in issue:
            logger.info("review command ignored", extra={"reason": "not_pull_request"})
            return {"ignored": True, "reason": "not_pull_request"}

        comment = payload.get("comment") or {}
        body = str(comment.get("body") or "")
        if not self._matches_review_command(body):
            logger.info("review command ignored", extra={"reason": "command_mismatch"})
            return {"ignored": True, "reason": "command_mismatch"}

        repo = payload["repository"]["full_name"]
        pr_number = int(issue["number"])
        username = str(comment.get("user", {}).get("login") or "")
        logger.append_keys(repo=repo, pr_number=pr_number, username=username)
        logger.info("review command received")

        installation = self.github_client.fetch_repository_installation(repo)
        installation_id = int(installation["id"])

        permission = self.github_client.fetch_collaborator_permission(
            repo=repo,
            username=username,
            installation_id=installation_id,
        )
        if permission not in ALLOWED_PERMISSIONS:
            logger.warning(
                "review command rejected: insufficient permission",
                extra={"permission": permission},
            )
            self.github_client.post_issue_comment(
                repo=repo,
                issue_number=pr_number,
                body=(
                    f"@{username} `/review` を実行する権限がありません。"
                    " write 以上の repository 権限が必要です。"
                ),
                installation_id=installation_id,
            )
            return {"ignored": True, "reason": "insufficient_permission"}

        pull_request = self.github_client.fetch_pull_request(
            repo=repo,
            pr_number=pr_number,
            installation_id=installation_id,
        )
        repository = self.github_client.fetch_repository(
            repo=repo,
            installation_id=installation_id,
        )
        ref = str(repository["default_branch"])
        inputs = self._workflow_inputs(
            pr_number=pr_number,
            pull_request=pull_request,
        )
        self.github_client.dispatch_review_workflow(
            repo=repo,
            ref=ref,
            inputs=inputs,
            installation_id=installation_id,
        )
        self.github_client.post_issue_comment(
            repo=repo,
            issue_number=pr_number,
            body=f"@{username} AI review を開始しました。",
            installation_id=installation_id,
        )
        logger.info("review workflow dispatched", extra={"ref": ref})
        return {"ignored": False, "dispatched": True}

    def _matches_review_command(self, body: str) -> bool:
        pattern = rf"(?i)(?:^|\s)@{re.escape(self.bot_name)}\s+/?review(?:\s|$)"
        return re.search(pattern, body) is not None

    def _workflow_inputs(
        self, pr_number: int, pull_request: dict[str, Any]
    ) -> dict[str, str]:
        head = pull_request["head"]
        base = pull_request["base"]
        head_repo = head.get("repo") or {}
        return {
            "pr_number": str(pr_number),
            "head_sha": str(head["sha"]),
            "base_sha": str(base["sha"]),
            "head_ref": str(head["ref"]),
            "base_ref": str(base["ref"]),
            "head_repo": str(head_repo.get("full_name") or ""),
            "pr_title": str(pull_request["title"]),
            "pr_author": str(pull_request["user"]["login"]),
        }
