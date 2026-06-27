from __future__ import annotations

from typing import Any


class RuleGeneratorStub:
    """Stub rule generator for local tests.

    Returns pre-registered decisions instead of calling an LLM so the extraction
    service can be exercised without network or API credentials.
    """

    def __init__(self, decisions: list[dict[str, Any]] | None = None) -> None:
        """Initialize the stub.

        Args:
            decisions: Decisions to return from :meth:`extract_rules`, such as
                ``[{"action": "create", "name": "controller/layer-violation",
                "package": "backend", "category": "code-quality", "body": "..."}]``.

        Returns:
            None. Example: ``RuleGeneratorStub([{"action": "reuse", "rule_id": "abc"}])``.
        """
        self.decisions = decisions or []
        self.calls: list[dict[str, Any]] = []

    def extract_rules(
        self,
        *,
        comments: list[dict[str, Any]],
        existing_rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Record the call and return the configured decisions.

        Args:
            comments: Candidate review comments passed by the service.
            existing_rules: Existing rules passed by the service.

        Returns:
            The decisions configured at construction time.
        """
        self.calls.append({"comments": comments, "existing_rules": existing_rules})
        return self.decisions
