from __future__ import annotations

from typing import Any


class GitHubApiStub:
    """Stub GitHub API client for local tests."""

    def __init__(self) -> None:
        """Initialize the stub storage.

        Args:
            None.

        Returns:
            None. Example: ``stub = GitHubApiStub()``.
        """
        self._labels_by_pr: dict[tuple[str, int], list[dict[str, Any]]] = {}

    def set_pr_labels(self, repo: str, pr_number: int, labels: list[str]) -> None:
        """Register labels returned for a PR.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            pr_number: Pull request number such as ``123``.
            labels: Label names such as ``["ai-eval:success", "ai-review:missed-issue"]``.

        Returns:
            None. Example: ``stub.set_pr_labels("owner/repo", 1, ["ai-eval:success"])``.
        """
        self._labels_by_pr[(repo, pr_number)] = [{"name": label} for label in labels]

    def fetch_pr_labels(self, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Return configured labels for a PR.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            pr_number: Pull request number such as ``123``.

        Returns:
            A list of label objects such as ``[{"name": "ai-eval:success"}]``.
        """
        return self._labels_by_pr.get((repo, pr_number), [])
