from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from observability import logger


GITHUB_API = "https://api.github.com"


class GitHubApiClient:
    """GitHub API client for fetching pull request labels."""

    def __init__(self, token: str) -> None:
        """Initialize the API client.

        Args:
            token: GitHub API token string such as ``"ghp_xxx"``.

        Returns:
            None. Example: ``GitHubApiClient(token="ghp_example")``.
        """
        self.token = token

    def fetch_pr_labels(self, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Fetch labels from a pull request issue endpoint.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            pr_number: Pull request number such as ``123``.

        Returns:
            A list of label objects such as ``[{"name": "ai-eval:success"}]``.
        """
        logger.debug("fetching PR labels", extra={"repo": repo, "pr_number": pr_number})
        url = f"{GITHUB_API}/repos/{repo}/issues/{pr_number}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            logger.warning(
                "GitHub API error fetching PR labels",
                extra={"repo": repo, "pr_number": pr_number, "status": error.code},
            )
            raise
        except urllib.error.URLError as error:
            logger.warning(
                "GitHub API network error fetching PR labels",
                extra={
                    "repo": repo,
                    "pr_number": pr_number,
                    "reason": str(error.reason),
                },
            )
            raise
        return payload.get("labels", [])
