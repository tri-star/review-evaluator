from __future__ import annotations

from infrastructures.github_api_stub import GitHubApiStub
from services.review_evaluation_service import ReviewEvaluationService


def test_成功ラベルがある場合は_success_になる() -> None:
    github_api_stub = GitHubApiStub()
    github_api_stub.set_pr_labels(
        repo="owner/repo",
        pr_number=101,
        labels=["ai-verdict:mergeable", "ai-eval:success"],
    )
    service = ReviewEvaluationService(github_api_client=github_api_stub)

    result = service.evaluate_review(
        review={
            "repo": "owner/repo",
            "pr_number": 101,
            "head_sha": "abc123",
            "run_at": "2026-04-16T01:00:00+00:00",
            "verdict": "mergeable",
        },
        evaluated_at="2026-04-16T06:00:00+00:00",
    )

    assert result["evaluation_status"] == "success"
    assert result["missed_issue"] is False
    assert result["false_positive"] is False


def test_失敗ラベルと補助ラベルがある場合は_failure_と補助指標が反映される() -> None:
    github_api_stub = GitHubApiStub()
    github_api_stub.set_pr_labels(
        repo="owner/repo",
        pr_number=102,
        labels=[
            "ai-eval:failure",
            "ai-review:missed-issue",
            "ai-review:false-positive",
        ],
    )
    service = ReviewEvaluationService(github_api_client=github_api_stub)

    result = service.evaluate_review(
        review={
            "repo": "owner/repo",
            "pr_number": 102,
            "head_sha": "def456",
            "run_at": "2026-04-16T02:00:00+00:00",
            "verdict": "human-review",
        },
        evaluated_at="2026-04-16T06:00:00+00:00",
    )

    assert result["evaluation_status"] == "failure"
    assert result["missed_issue"] is True
    assert result["false_positive"] is True


def test_評価ラベルが無い場合は_excluded_になる() -> None:
    service = ReviewEvaluationService(github_api_client=GitHubApiStub())

    result = service.evaluate_review(
        review={
            "repo": "owner/repo",
            "pr_number": 103,
            "head_sha": "ghi789",
            "run_at": "2026-04-16T03:00:00+00:00",
            "verdict": "mergeable",
        },
        evaluated_at="2026-04-16T06:00:00+00:00",
    )

    assert result["evaluation_status"] == "excluded"


def test_head_shaが無いreviewでも評価できる() -> None:
    github_api_stub = GitHubApiStub()
    github_api_stub.set_pr_labels(
        repo="owner/repo",
        pr_number=104,
        labels=["ai-eval:success"],
    )
    service = ReviewEvaluationService(github_api_client=github_api_stub)

    result = service.evaluate_review(
        review={
            "repo": "owner/repo",
            "pr_number": 104,
            "run_at": "2026-04-16T04:00:00+00:00",
            "verdict": "mergeable",
        },
        evaluated_at="2026-04-16T06:00:00+00:00",
    )

    assert result["evaluation_status"] == "success"
    assert result["head_sha"] is None


def test_日次サマリで_precision_と件数を集計できる() -> None:
    service = ReviewEvaluationService(github_api_client=None)
    evaluations = [
        {
            "verdict": "mergeable",
            "evaluation_status": "success",
            "missed_issue": False,
            "false_positive": False,
        },
        {
            "verdict": "mergeable",
            "evaluation_status": "failure",
            "missed_issue": False,
            "false_positive": True,
        },
        {
            "verdict": "human-review",
            "evaluation_status": "success",
            "missed_issue": True,
            "false_positive": False,
        },
        {
            "verdict": "mergeable",
            "evaluation_status": "excluded",
            "missed_issue": False,
            "false_positive": False,
        },
    ]

    summary = service.build_daily_summary(
        repo="owner/repo",
        target_date="2026-04-16",
        evaluations=evaluations,
    )

    assert summary["review_runs"] == 4
    assert summary["evaluated_runs"] == 3
    assert summary["excluded_runs"] == 1
    assert summary["mergeable"]["total"] == 2
    assert summary["mergeable"]["precision"] == 0.5
    assert summary["human_review"]["total"] == 1
    assert summary["human_review"]["precision"] == 1.0
    assert summary["missed_issue_count"] == 1
    assert summary["false_positive_count"] == 1


def test_週次サマリで_iso_week_を含む() -> None:
    service = ReviewEvaluationService(github_api_client=None)

    summary = service.build_weekly_summary(
        repo="owner/repo",
        target_date="2026-04-20",
        evaluations=[
            {
                "verdict": "mergeable",
                "evaluation_status": "success",
                "missed_issue": False,
                "false_positive": False,
            }
        ],
    )

    assert summary["week"] == "2026-W17"
    assert summary["mergeable"]["precision"] == 1.0
