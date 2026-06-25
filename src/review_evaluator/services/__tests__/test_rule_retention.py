from __future__ import annotations

from datetime import datetime, timezone

from services.rule_retention import select_prunable_rules


NOW = datetime(2026, 6, 25, tzinfo=timezone.utc)


def _rule(rule_id: str, last_used: str | None) -> dict[str, object]:
    return {"rule_id": rule_id, "recent_usage": [last_used] if last_used else []}


def test_keeps_all_rules_when_under_max_count() -> None:
    rules = [_rule("r1", None), _rule("r2", "2020-01-01T00:00:00+00:00")]

    assert select_prunable_rules(rules, now=NOW, max_count=10) == []


def test_prunes_least_recently_used_stale_rules_down_to_max() -> None:
    rules = [
        _rule("fresh", "2026-06-20T00:00:00+00:00"),
        _rule("old-a", "2024-01-01T00:00:00+00:00"),
        _rule("never", None),
        _rule("old-b", "2025-01-01T00:00:00+00:00"),
    ]

    result = select_prunable_rules(rules, now=NOW, retention_days=90, max_count=2)

    # 上限2件に対し4件あるので2件削除。未使用と最古を優先する。
    assert result == ["never", "old-a"]


def test_does_not_prune_recently_used_rules_even_when_over_capacity() -> None:
    rules = [
        _rule("a", "2026-06-24T00:00:00+00:00"),
        _rule("b", "2026-06-23T00:00:00+00:00"),
        _rule("c", "2026-06-22T00:00:00+00:00"),
    ]

    # 全て直近利用のため、上限超過でも削除対象なし。
    assert select_prunable_rules(rules, now=NOW, retention_days=90, max_count=1) == []
