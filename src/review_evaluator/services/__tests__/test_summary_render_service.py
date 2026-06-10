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
            "human_review": {
                "total": 3,
                "success": 2,
                "failure": 1,
                "precision": 2 / 3,
            },
            "missed_issue_count": 1,
            "false_positive_count": 0,
        },
        recent_summary={
            "label": "Last 7 days",
            "start_date": "2026-04-10",
            "end_date": "2026-04-16",
            "review_runs": 30,
            "evaluated_runs": 25,
            "excluded_runs": 5,
            "mergeable": {"total": 16, "success": 12, "failure": 4, "precision": 0.75},
            "human_review": {
                "total": 9,
                "success": 5,
                "failure": 4,
                "precision": 5 / 9,
            },
            "missed_issue_count": 2,
            "false_positive_count": 1,
        },
        all_time_summary={
            "label": "All-time",
            "start_date": None,
            "end_date": None,
            "review_runs": 100,
            "evaluated_runs": 80,
            "excluded_runs": 20,
            "mergeable": {"total": 50, "success": 40, "failure": 10, "precision": 0.8},
            "human_review": {
                "total": 30,
                "success": 20,
                "failure": 10,
                "precision": 2 / 3,
            },
            "missed_issue_count": 8,
            "false_positive_count": 4,
        },
    )

    assert "# AI Review Daily Summary" in body
    assert "## Last 7 days Summary" in body
    assert "2026-04-10" in body
    assert "## All-time Summary" in body
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
            "human_review": {
                "total": 3,
                "success": 2,
                "failure": 1,
                "precision": 2 / 3,
            },
            "missed_issue_count": 1,
            "false_positive_count": 0,
        },
        recent_summary={
            "label": "Last 7 days",
            "start_date": "2026-04-10",
            "end_date": "2026-04-16",
            "review_runs": 30,
            "evaluated_runs": 25,
            "excluded_runs": 5,
            "mergeable": {"total": 16, "success": 12, "failure": 4, "precision": 0.75},
            "human_review": {
                "total": 9,
                "success": 5,
                "failure": 4,
                "precision": 5 / 9,
            },
            "missed_issue_count": 2,
            "false_positive_count": 1,
        },
        all_time_summary={
            "label": "All-time",
            "start_date": None,
            "end_date": None,
            "review_runs": 100,
            "evaluated_runs": 80,
            "excluded_runs": 20,
            "mergeable": {"total": 50, "success": 40, "failure": 10, "precision": 0.8},
            "human_review": {
                "total": 30,
                "success": 20,
                "failure": 10,
                "precision": 2 / 3,
            },
            "missed_issue_count": 8,
            "false_positive_count": 4,
        },
    )

    assert "AI Review Daily Summary - 2026-04-16" in text
    assert "Repo: owner/repo" in text
    assert "Missed issues: 1" in text
    assert "Last 7 days: 2026-04-10 - 2026-04-16" in text
    assert "All-time" in text
