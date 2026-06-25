from __future__ import annotations

from typing import Any

from infrastructures.rule_generator_stub import RuleGeneratorStub
from services.rule_extraction_service import RuleExtractionService


class FakeRuleStore:
    def __init__(self, rules: list[dict[str, Any]] | None = None) -> None:
        self.rules = list(rules or [])
        self.saved: list[dict[str, Any]] = []
        self.usage: list[tuple[str, str]] = []

    def list_rules(self) -> list[dict[str, Any]]:
        return self.rules

    def save_rule(self, rule: dict[str, Any]) -> None:
        self.saved.append(rule)
        self.rules.append(rule)

    def append_usage(self, rule_id: str, used_at: str) -> None:
        self.usage.append((rule_id, used_at))


class FakeGitHubClient:
    def __init__(
        self,
        issue_comments: list[dict[str, Any]],
        review_comments: list[dict[str, Any]],
    ) -> None:
        self.issue_comments = issue_comments
        self.review_comments = review_comments
        self.calls: list[tuple[Any, ...]] = []

    def fetch_repository_installation(self, repo: str) -> dict[str, Any]:
        self.calls.append(("fetch_repository_installation", repo))
        return {"id": 42}

    def fetch_pr_issue_comments(
        self, repo: str, pr_number: int, installation_id: int
    ) -> list[dict[str, Any]]:
        self.calls.append(("fetch_pr_issue_comments", repo, pr_number, installation_id))
        return self.issue_comments

    def fetch_pr_review_comments(
        self, repo: str, pr_number: int, installation_id: int
    ) -> list[dict[str, Any]]:
        self.calls.append(
            ("fetch_pr_review_comments", repo, pr_number, installation_id)
        )
        return self.review_comments


def _service(
    *,
    github_client: FakeGitHubClient,
    rule_store: FakeRuleStore,
    decisions: list[dict[str, Any]],
) -> RuleExtractionService:
    ids = iter(["id-1", "id-2", "id-3"])
    return RuleExtractionService(
        github_client=github_client,
        rule_store=rule_store,
        rule_generator=RuleGeneratorStub(decisions),
        now_factory=lambda: "2026-06-25T00:00:00+00:00",
        id_factory=lambda: next(ids),
    )


def test_chatter_and_bot_comments_are_excluded_from_candidates() -> None:
    github_client = FakeGitHubClient(
        issue_comments=[
            {
                "body": "ありがとうございます",
                "user": {"login": "alice", "type": "User"},
            },
            {"body": "", "user": {"login": "alice", "type": "User"}},
            {
                "body": "ここはControllerにビジネスロジックを書かず、Service層に移してください。",
                "user": {"login": "alice", "type": "User"},
            },
        ],
        review_comments=[
            {
                "body": "LGTM <!-- RuleId: existing-1 -->",
                "user": {"login": "review-bot", "type": "Bot"},
                "path": "src/api/foo.ts",
            },
        ],
    )
    store = FakeRuleStore()
    generator = RuleGeneratorStub([])
    service = RuleExtractionService(
        github_client=github_client,
        rule_store=store,
        rule_generator=generator,
        now_factory=lambda: "2026-06-25T00:00:00+00:00",
    )

    service.handle(repo="owner/repo", pr_number=1)

    # 短すぎる相槌・空コメント・Bot/マーカー付きコメントは候補から除外される。
    assert len(generator.calls) == 1
    candidates = generator.calls[0]["comments"]
    assert len(candidates) == 1
    assert "Service層" in candidates[0]["body"]


def test_marker_in_any_comment_records_usage() -> None:
    github_client = FakeGitHubClient(
        issue_comments=[
            {
                "body": "適用済み <!-- RuleId: rule-a --> <!-- RuleId: rule-b -->",
                "user": {"login": "review-bot", "type": "Bot"},
            },
        ],
        review_comments=[],
    )
    store = FakeRuleStore()
    service = _service(github_client=github_client, rule_store=store, decisions=[])

    result = service.handle(repo="owner/repo", pr_number=1)

    assert result["usage_updates"] == 2
    assert store.usage == [
        ("rule-a", "2026-06-25T00:00:00+00:00"),
        ("rule-b", "2026-06-25T00:00:00+00:00"),
    ]


def test_create_decision_persists_rule_with_seeded_usage() -> None:
    github_client = FakeGitHubClient(
        issue_comments=[
            {
                "body": "Controllerにロジックを書かないでください。Service層へ移動を。",
                "user": {"login": "alice", "type": "User"},
            }
        ],
        review_comments=[],
    )
    store = FakeRuleStore()
    service = _service(
        github_client=github_client,
        rule_store=store,
        decisions=[
            {
                "action": "create",
                "name": "controller/layer-violation",
                "package": "backend",
                "category": "code-quality",
                "body": "Controller層にビジネスロジックを書かない。",
            }
        ],
    )

    result = service.handle(repo="owner/repo", pr_number=1)

    assert result["created_rules"] == 1
    assert store.saved == [
        {
            "rule_id": "id-1",
            "name": "controller/layer-violation",
            "package": "backend",
            "category": "code-quality",
            "body": "Controller層にビジネスロジックを書かない。",
            "recent_usage": ["2026-06-25T00:00:00+00:00"],
        }
    ]


def test_reuse_decision_does_not_create_rule() -> None:
    github_client = FakeGitHubClient(
        issue_comments=[
            {
                "body": "これは既存ルールと同じ指摘になりますね、注意してください。",
                "user": {"login": "alice", "type": "User"},
            }
        ],
        review_comments=[],
    )
    store = FakeRuleStore(rules=[{"rule_id": "existing-1", "name": "x/y"}])
    service = _service(
        github_client=github_client,
        rule_store=store,
        decisions=[{"action": "reuse", "rule_id": "existing-1"}],
    )

    result = service.handle(repo="owner/repo", pr_number=1)

    assert result == {
        "repo": "owner/repo",
        "pr_number": 1,
        "created_rules": 0,
        "reused_rules": 1,
        "usage_updates": 0,
        "candidate_comments": 1,
    }
    assert store.saved == []


def test_invalid_create_decision_is_skipped() -> None:
    github_client = FakeGitHubClient(
        issue_comments=[
            {
                "body": "この指摘はルール化したいが、パッケージが不明なケースです。",
                "user": {"login": "alice", "type": "User"},
            }
        ],
        review_comments=[],
    )
    store = FakeRuleStore()
    service = _service(
        github_client=github_client,
        rule_store=store,
        decisions=[
            {"action": "create", "name": "x/y", "package": "infra", "body": "..."},
            {"action": "create", "name": "", "package": "backend", "body": "..."},
        ],
    )

    result = service.handle(repo="owner/repo", pr_number=1)

    assert result["created_rules"] == 0
    assert store.saved == []


def test_no_candidates_skips_generator() -> None:
    github_client = FakeGitHubClient(
        issue_comments=[{"body": "thanks", "user": {"login": "a", "type": "User"}}],
        review_comments=[],
    )
    store = FakeRuleStore()
    generator = RuleGeneratorStub([])
    service = RuleExtractionService(
        github_client=github_client,
        rule_store=store,
        rule_generator=generator,
        now_factory=lambda: "2026-06-25T00:00:00+00:00",
    )

    result = service.handle(repo="owner/repo", pr_number=1)

    assert result["candidate_comments"] == 0
    assert generator.calls == []
