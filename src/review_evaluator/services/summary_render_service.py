from __future__ import annotations

from typing import Any


class SummaryRenderService:
    """Render GitHub issue and Slack summary texts from aggregate data."""

    def render_issue_body(
        self, daily_summary: dict[str, Any], weekly_summary: dict[str, Any] | None
    ) -> str:
        """Render the GitHub issue markdown body from aggregate summaries.

        Args:
            daily_summary: Daily summary dict such as ``{"date": "2026-04-16", "repo": "owner/repo"}``.
            weekly_summary: Weekly summary dict such as ``{"week": "2026-W17"}`` or ``None``.

        Returns:
            Markdown body text such as ``"# AI Review Daily Summary\n..."``.
        """
        lines = [
            "# AI Review Daily Summary",
            "",
            f"- Date: `{daily_summary['date']}`",
            f"- Repo: `{daily_summary['repo']}`",
            f"- Review runs: `{daily_summary['review_runs']}`",
            f"- Evaluated: `{daily_summary['evaluated_runs']}`",
            f"- Excluded: `{daily_summary['excluded_runs']}`",
            "",
            "## Precision",
            f"- Mergeable: `{daily_summary['mergeable']['success']}/{daily_summary['mergeable']['total']}` ({daily_summary['mergeable']['precision']:.2%})",
            f"- Human review: `{daily_summary['human_review']['success']}/{daily_summary['human_review']['total']}` ({daily_summary['human_review']['precision']:.2%})",
            "",
            "## Auxiliary Metrics",
            f"- Missed issues: `{daily_summary['missed_issue_count']}`",
            f"- False positives: `{daily_summary['false_positive_count']}`",
        ]
        if weekly_summary:
            lines.extend(
                [
                    "",
                    "## Weekly Summary",
                    f"- Week: `{weekly_summary['week']}`",
                    f"- Review runs: `{weekly_summary['review_runs']}`",
                    f"- Mergeable precision: `{weekly_summary['mergeable']['precision']:.2%}`",
                    f"- Human review precision: `{weekly_summary['human_review']['precision']:.2%}`",
                ]
            )
        return "\n".join(lines) + "\n"

    def render_slack_text(
        self, daily_summary: dict[str, Any], weekly_summary: dict[str, Any] | None
    ) -> str:
        """Render a plain text Slack message from aggregate summaries.

        Args:
            daily_summary: Daily summary dict such as ``{"date": "2026-04-16"}``.
            weekly_summary: Weekly summary dict such as ``{"week": "2026-W17"}`` or ``None``.

        Returns:
            Slack message text such as ``"AI Review Daily Summary - 2026-04-16\n..."``.
        """
        lines = [
            f"AI Review Daily Summary - {daily_summary['date']}",
            f"Repo: {daily_summary['repo']}",
            f"Review runs: {daily_summary['review_runs']}",
            f"Evaluated: {daily_summary['evaluated_runs']} / Excluded: {daily_summary['excluded_runs']}",
            f"Mergeable precision: {daily_summary['mergeable']['precision']:.0%} ({daily_summary['mergeable']['success']}/{daily_summary['mergeable']['total']})",
            f"Human-review precision: {daily_summary['human_review']['precision']:.0%} ({daily_summary['human_review']['success']}/{daily_summary['human_review']['total']})",
            f"Missed issues: {daily_summary['missed_issue_count']}",
            f"False positives: {daily_summary['false_positive_count']}",
        ]
        if weekly_summary:
            lines.extend(
                [
                    "",
                    f"Weekly summary: {weekly_summary['week']}",
                    f"Mergeable precision: {weekly_summary['mergeable']['precision']:.0%}",
                    f"Human-review precision: {weekly_summary['human_review']['precision']:.0%}",
                ]
            )
        return "\n".join(lines)
