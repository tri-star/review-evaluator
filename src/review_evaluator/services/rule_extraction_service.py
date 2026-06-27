from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol

from observability import logger


# レビューと無関係な相槌（「ありがとうございます」等）や空コメントを
# LLM へ渡す前に落とすための最小長。本格的な判定は LLM 側に委ねる。
MIN_COMMENT_LENGTH = 15

# レビューエージェントが付与する利用マーカー。安定キーである rule_id を抽出する。
MARKER_PATTERN = re.compile(r"<!--\s*RuleId:\s*([0-9A-Za-z-]+)\s*-->")

VALID_PACKAGES = {"frontend", "backend"}


class RuleStore(Protocol):
    """Protocol for the rule persistence layer."""

    def list_rules(self) -> list[dict[str, Any]]:
        """Return all stored rules such as ``[{"rule_id": "...", "name": "..."}]``."""

    def save_rule(self, rule: dict[str, Any]) -> None:
        """Persist a single rule dict."""

    def append_usage(self, rule_id: str, used_at: str) -> None:
        """Append a usage timestamp to an existing rule, ignoring unknown ids."""


class RuleGenerator(Protocol):
    """Protocol for the LLM-backed rule classifier/generator."""

    def extract_rules(
        self,
        *,
        comments: list[dict[str, Any]],
        existing_rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Classify candidate comments into rule decisions.

        Args:
            comments: Candidate review comments such as
                ``[{"body": "...", "path": "src/foo.ts"}]``.
            existing_rules: Currently stored rules used for de-duplication.

        Returns:
            Decisions such as
            ``[{"action": "create", "name": "controller/layer-violation",
            "package": "backend", "category": "code-quality", "body": "..."},
            {"action": "reuse", "rule_id": "abc-123"}]``.
            Comments judged as non-review chatter are omitted.
        """


class RuleExtractionGitHubClient(Protocol):
    """Protocol for the GitHub client used during rule extraction."""

    def fetch_repository_installation(self, repo: str) -> dict[str, Any]: ...

    def fetch_pr_issue_comments(
        self, repo: str, pr_number: int, installation_id: int
    ) -> list[dict[str, Any]]: ...

    def fetch_pr_review_comments(
        self, repo: str, pr_number: int, installation_id: int
    ) -> list[dict[str, Any]]: ...


class RuleExtractionService:
    """Extract reusable review rules from a pull request's comments."""

    def __init__(
        self,
        github_client: RuleExtractionGitHubClient,
        rule_store: RuleStore,
        rule_generator: RuleGenerator,
        *,
        now_factory: Callable[[], str] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            github_client: GitHub client for fetching PR comments.
            rule_store: Persistence layer for rules.
            rule_generator: LLM-backed classifier that turns comments into rule decisions.
            now_factory: Callable returning the current ISO 8601 timestamp. Injected for tests.
            id_factory: Callable returning a new rule id. Injected for tests.

        Returns:
            None.
        """
        self.github_client = github_client
        self.rule_store = rule_store
        self.rule_generator = rule_generator
        self._now = now_factory or (lambda: datetime.now(timezone.utc).isoformat())
        self._new_id = id_factory or (lambda: str(uuid.uuid4()))

    def handle(self, repo: str, pr_number: int) -> dict[str, Any]:
        """Extract rules and record rule usage for a single closed pull request.

        Args:
            repo: Repository full name such as ``"owner/repo"``.
            pr_number: Pull request number such as ``123``.

        Returns:
            A result summary such as
            ``{"created_rules": 1, "reused_rules": 2, "usage_updates": 3, "candidate_comments": 4}``.
        """
        logger.append_keys(repo=repo, pr_number=pr_number)

        installation = self.github_client.fetch_repository_installation(repo)
        installation_id = int(installation["id"])

        comments = [
            *self.github_client.fetch_pr_issue_comments(
                repo=repo, pr_number=pr_number, installation_id=installation_id
            ),
            *self.github_client.fetch_pr_review_comments(
                repo=repo, pr_number=pr_number, installation_id=installation_id
            ),
        ]
        logger.info("PR comments loaded", extra={"count": len(comments)})

        usage_updates = self._record_rule_usage(comments)
        candidates = self._candidate_comments(comments)
        logger.info(
            "extraction candidates resolved",
            extra={
                "candidate_comments": len(candidates),
                "usage_updates": usage_updates,
            },
        )

        created, reused = self._extract_rules(candidates)

        result = {
            "repo": repo,
            "pr_number": pr_number,
            "created_rules": created,
            "reused_rules": reused,
            "usage_updates": usage_updates,
            "candidate_comments": len(candidates),
        }
        logger.info("rule extraction completed", extra=result)
        return result

    def _record_rule_usage(self, comments: list[dict[str, Any]]) -> int:
        """Append usage timestamps for every rule marker found in the comments.

        Args:
            comments: Raw PR comment objects.

        Returns:
            The number of usage timestamps appended.
        """
        used_at = self._now()
        seen: set[str] = set()
        unique_ids: list[str] = []
        for comment in comments:
            body = str(comment.get("body") or "")
            for rule_id in MARKER_PATTERN.findall(body):
                if rule_id not in seen:
                    seen.add(rule_id)
                    unique_ids.append(rule_id)
        for rule_id in unique_ids:
            self.rule_store.append_usage(rule_id=rule_id, used_at=used_at)
        return len(unique_ids)

    def _candidate_comments(
        self, comments: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Filter comments down to human-authored review candidates.

        Bot-authored comments and comments that carry a rule marker are excluded
        so the bot never learns rules from its own review output. Empty or very
        short comments are dropped as obvious non-review chatter.

        Args:
            comments: Raw PR comment objects.

        Returns:
            Candidate comments such as ``[{"body": "...", "path": "src/foo.ts"}]``.
        """
        candidates: list[dict[str, Any]] = []
        for comment in comments:
            user = comment.get("user") or {}
            if str(user.get("type")) == "Bot":
                continue
            body = str(comment.get("body") or "").strip()
            if len(body) < MIN_COMMENT_LENGTH:
                continue
            if MARKER_PATTERN.search(body):
                continue
            candidates.append({"body": body, "path": comment.get("path")})
        return candidates

    def _extract_rules(self, candidates: list[dict[str, Any]]) -> tuple[int, int]:
        """Run the generator over candidates and persist newly created rules.

        Args:
            candidates: Candidate review comments.

        Returns:
            A ``(created_count, reused_count)`` tuple.
        """
        if not candidates:
            return 0, 0

        existing_rules = self.rule_store.list_rules()
        decisions = self.rule_generator.extract_rules(
            comments=candidates, existing_rules=existing_rules
        )

        created = 0
        reused = 0
        saved_keys: set[tuple[str, str]] = set()
        for decision in decisions:
            action = decision.get("action")
            if action == "reuse":
                rule_id = decision.get("rule_id")
                if rule_id:
                    self.rule_store.append_usage(rule_id=rule_id, used_at=self._now())
                reused += 1
                continue
            if action == "create":
                rule = self._build_rule(decision)
                if rule is None:
                    continue
                key = (rule["name"], rule["package"])
                if key in saved_keys:
                    logger.warning(
                        "duplicate rule create skipped",
                        extra={"rule_name": rule["name"], "package": rule["package"]},
                    )
                    continue
                saved_keys.add(key)
                self.rule_store.save_rule(rule)
                created += 1
                logger.info(
                    "rule created",
                    extra={"rule_id": rule["rule_id"], "rule_name": rule["name"]},
                )
                continue
            logger.warning("unexpected rule decision skipped", extra={"action": action})
        return created, reused

    def _build_rule(self, decision: dict[str, Any]) -> dict[str, Any] | None:
        """Build a storable rule dict from a ``create`` decision.

        A freshly extracted rule has not been applied by the reviewer yet, so its
        ``recent_usage`` is seeded with the creation time. This keeps brand-new
        rules from being culled immediately by the low-usage cleanup job.

        Args:
            decision: A ``create`` decision from the generator.

        Returns:
            A rule dict, or ``None`` when the decision is malformed.
        """
        package = str(decision.get("package") or "")
        name = str(decision.get("name") or "").strip()
        body = str(decision.get("body") or "").strip()
        if package not in VALID_PACKAGES or not name or not body:
            logger.warning(
                "invalid rule decision skipped",
                extra={"rule_name": name, "package": package, "has_body": bool(body)},
            )
            return None
        return {
            "rule_id": self._new_id(),
            "name": name,
            "package": package,
            "category": str(decision.get("category") or "uncategorized").strip(),
            "body": body,
            "recent_usage": [self._now()],
        }
