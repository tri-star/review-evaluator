from __future__ import annotations

import json
import urllib.request

from observability import logger


GITHUB_API = "https://api.github.com"


class GitHubSummaryPublisher:
    """Publish daily and weekly summaries to a fixed GitHub issue."""

    def __init__(self, token: str) -> None:
        """Initialize the publisher.

        Args:
            token: GitHub API token string such as ``"ghp_example"``.

        Returns:
            None. Example: ``GitHubSummaryPublisher(token="ghp_example")``.
        """
        self.token = token

    def update_summary_issue(
        self,
        repo: str,
        issue_number: str,
        body: str,
    ) -> None:
        """Update the fixed GitHub summary issue with the latest aggregates.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            issue_number: Target issue number such as ``"12"``.
            body: GitHub issue markdown body such as ``"# AI Review Daily Summary\n..."``.

        Returns:
            None. The issue body is replaced via GitHub REST API.
        """
        logger.info(
            "updating GitHub summary issue",
            extra={"repo": repo, "issue_number": issue_number},
        )
        request = urllib.request.Request(
            f"{GITHUB_API}/repos/{repo}/issues/{issue_number}",
            method="PATCH",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            data=json.dumps({"body": body}).encode("utf-8"),
        )
        with urllib.request.urlopen(request, timeout=20):
            pass
        logger.info("GitHub summary issue updated")
