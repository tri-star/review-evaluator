from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

import jwt

from observability import logger


GITHUB_API = "https://api.github.com"


class GitHubApiError(Exception):
    """GitHub API request failed."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


class GitHubAppClient:
    """GitHub App installation client for review command webhooks."""

    def __init__(
        self,
        app_id: str,
        private_key: str,
        *,
        api_base: str = GITHUB_API,
    ) -> None:
        self.app_id = app_id
        self.private_key = private_key
        self.api_base = api_base
        self._installation_tokens: dict[int, str] = {}

    def fetch_repository_installation(self, repo: str) -> dict[str, Any]:
        token = self._create_app_jwt()
        return self._request_json(
            "GET",
            f"/repos/{repo}/installation",
            token=token,
            expected_statuses={200},
        )

    def fetch_collaborator_permission(
        self, repo: str, username: str, installation_id: int
    ) -> str:
        try:
            payload = self._request_json(
                "GET",
                f"/repos/{repo}/collaborators/{username}/permission",
                token=self._installation_token(installation_id),
                expected_statuses={200},
            )
        except GitHubApiError as error:
            if error.status == 404:
                return "none"
            raise
        return str(payload.get("permission", "none"))

    def fetch_pull_request(
        self, repo: str, pr_number: int, installation_id: int
    ) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/repos/{repo}/pulls/{pr_number}",
            token=self._installation_token(installation_id),
            expected_statuses={200},
        )

    def fetch_repository(self, repo: str, installation_id: int) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/repos/{repo}",
            token=self._installation_token(installation_id),
            expected_statuses={200},
        )

    def dispatch_review_workflow(
        self,
        repo: str,
        ref: str,
        inputs: dict[str, str],
        installation_id: int,
    ) -> None:
        self._request_json(
            "POST",
            f"/repos/{repo}/actions/workflows/pr-ai-review.yml/dispatches",
            token=self._installation_token(installation_id),
            payload={"ref": ref, "inputs": inputs},
            expected_statuses={204},
        )

    def post_issue_comment(
        self, repo: str, issue_number: int, body: str, installation_id: int
    ) -> None:
        self._request_json(
            "POST",
            f"/repos/{repo}/issues/{issue_number}/comments",
            token=self._installation_token(installation_id),
            payload={"body": body},
            expected_statuses={201},
        )

    def fetch_pr_issue_comments(
        self, repo: str, pr_number: int, installation_id: int
    ) -> list[dict[str, Any]]:
        """Fetch issue-level (conversation) comments on a pull request."""
        return self._request_paginated(
            f"/repos/{repo}/issues/{pr_number}/comments",
            token=self._installation_token(installation_id),
        )

    def fetch_pr_review_comments(
        self, repo: str, pr_number: int, installation_id: int
    ) -> list[dict[str, Any]]:
        """Fetch inline review comments on a pull request."""
        return self._request_paginated(
            f"/repos/{repo}/pulls/{pr_number}/comments",
            token=self._installation_token(installation_id),
        )

    def _request_paginated(
        self, path: str, *, token: str, per_page: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a GitHub list endpoint.

        Args:
            path: API path such as ``"/repos/owner/repo/issues/1/comments"``.
            token: Installation access token.
            per_page: Page size such as ``100``.

        Returns:
            The concatenated list of items across all pages.
        """
        separator = "&" if "?" in path else "?"
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._request_json(
                "GET",
                f"{path}{separator}per_page={per_page}&page={page}",
                token=token,
                expected_statuses={200},
            )
            batch = payload if isinstance(payload, list) else []
            items.extend(batch)
            if len(batch) < per_page:
                return items
            page += 1

    def _installation_token(self, installation_id: int) -> str:
        token = self._installation_tokens.get(installation_id)
        if token:
            return token

        payload = self._request_json(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            token=self._create_app_jwt(),
            expected_statuses={201},
        )
        token = str(payload["token"])
        self._installation_tokens[installation_id] = token
        return token

    def _create_app_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iat": now - 60,
                "exp": now + 600,
                "iss": self.app_id,
            },
            self.private_key,
            algorithm="RS256",
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        token: str,
        expected_statuses: set[int],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{self.api_base}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        logger.debug("GitHub App API request", extra={"method": method, "path": path})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status = response.status
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            status = error.code
            body = error.read().decode("utf-8")
        except urllib.error.URLError as error:
            logger.warning(
                "GitHub App API network error",
                extra={"method": method, "path": path, "reason": str(error.reason)},
            )
            raise GitHubApiError(
                status=502,
                message=f"GitHub API network error: {error.reason}",
            ) from error
        if status not in expected_statuses:
            logger.warning(
                "GitHub App API unexpected status",
                extra={"method": method, "path": path, "status": status},
            )
            raise GitHubApiError(
                status=status,
                message=f"GitHub API failed: {status}. Response: {body}",
            )
        logger.debug(
            "GitHub App API response",
            extra={"method": method, "path": path, "status": status},
        )
        if not body:
            return {}
        return json.loads(body)
