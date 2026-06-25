from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


# 通常はルールを保持し続け、件数が増えすぎたときだけ低利用ルールを削る。
DEFAULT_MAX_RULE_COUNT = 100
DEFAULT_RETENTION_DAYS = 90

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def select_prunable_rules(
    rules: list[dict[str, Any]],
    *,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    max_count: int = DEFAULT_MAX_RULE_COUNT,
) -> list[str]:
    """Pick low-usage rule ids to delete when the rule set grows too large.

    Rules are only pruned when the total exceeds ``max_count``. Among rules whose
    most recent usage is older than ``retention_days``, the least-recently-used
    are removed first, down to ``max_count``.

    Args:
        rules: Stored rule dicts, each with an optional ``recent_usage`` list.
        now: Current time as an aware datetime.
        retention_days: A rule is prunable only if unused for at least this many days.
        max_count: Target maximum number of rules to keep.

    Returns:
        Rule ids to delete, such as ``["rule-a", "rule-b"]``.
    """
    if len(rules) <= max_count:
        return []

    cutoff = now - timedelta(days=retention_days)
    stale = [rule for rule in rules if _last_used(rule) < cutoff]
    stale.sort(key=_last_used)

    over_capacity = len(rules) - max_count
    return [rule["rule_id"] for rule in stale[:over_capacity]]


def _last_used(rule: dict[str, Any]) -> datetime:
    """Return the most recent usage timestamp, or the epoch when never used."""
    usage = rule.get("recent_usage") or []
    latest = _EPOCH
    for entry in usage:
        try:
            parsed = datetime.fromisoformat(str(entry).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        latest = max(latest, parsed)
    return latest
