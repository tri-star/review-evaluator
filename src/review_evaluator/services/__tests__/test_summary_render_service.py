from __future__ import annotations

from services.summary_render_service import SummaryRenderService


def test_GitHub_issue本文を生成できる() -> None:
    service = SummaryRenderService()

    body = service.render_issue_body(
        daily_summary={
            "date": "2026-04-16",
            "repo": "owner/repo",
            "review_runs": 10,
            "evaluated_runs": 8,
            "excluded_runs": 2,
            "mergeable": {"total": 5, "success": 4, "failure": 1, "precision": 0.8},
            "human_review": {"total": 3, "success": 2, "failure": 1, "precision": 2 / 3},
            "missed_issue_count": 1,
            "false_positive_count": 0,
        },
        weekly_summary={
            "week": "2026-W16",
            "review_runs": 30,
            "mergeable": {"precision": 0.75},
            "human_review": {"precision": 0.5},
        },
    )

    assert "# AI Review Daily Summary" in body
    assert "2026-W16" in body
    assert "Missed issues" in body


def test_Slack本文を生成できる() -> None:
    service = SummaryRenderService()

    text = service.render_slack_text(
        daily_summary={
            "date": "2026-04-16",
            "repo": "owner/repo",
            "review_runs": 10,
            "evaluated_runs": 8,
            "excluded_runs": 2,
            "mergeable": {"total": 5, "success": 4, "failure": 1, "precision": 0.8},
            "human_review": {"total": 3, "success": 2, "failure": 1, "precision": 2 / 3},
            "missed_issue_count": 1,
            "false_positive_count": 0,
        },
        weekly_summary=None,
    )

    assert "AI Review Daily Summary - 2026-04-16" in text
    assert "Repo: owner/repo" in text
    assert "Missed issues: 1" in text
