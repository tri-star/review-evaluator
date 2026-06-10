from __future__ import annotations

from typing import Any


class SummaryRenderService:
    """Render GitHub issue and Slack summary texts from aggregate data."""

    def render_issue_body(
        self,
        daily_summary: dict[str, Any],
        recent_summary: dict[str, Any],
        all_time_summary: dict[str, Any],
    ) -> str:
        """Render the GitHub issue markdown body from aggregate summaries.

        Args:
            daily_summary: Daily summary dict such as ``{"date": "2026-04-16", "repo": "owner/repo"}``.
            recent_summary: Rolling-period summary such as ``{"label": "Last 7 days"}``.
            all_time_summary: All-time summary such as ``{"label": "All-time"}``.

        Returns:
            Markdown body text such as ``"# AI Review Daily Summary\n..."``.
        """
        lines = [
            "# AI Review Daily Summary",
            "",
            f"- Date: `{daily_summary['date']}`",
            f"- Repo: `{daily_summary['repo']}`",
            "",
            "## Daily Summary",
            "",
            f"- Review runs: `{daily_summary['review_runs']}`",
            f"- Evaluated: `{daily_summary['evaluated_runs']}`",
            f"- Excluded: `{daily_summary['excluded_runs']}`",
            "",
            "### Precision",
            f"- Mergeable: `{daily_summary['mergeable']['success']}/{daily_summary['mergeable']['total']}` ({daily_summary['mergeable']['precision']:.2%})",
            f"- Human review: `{daily_summary['human_review']['success']}/{daily_summary['human_review']['total']}` ({daily_summary['human_review']['precision']:.2%})",
            "",
            "### Auxiliary Metrics",
            f"- Missed issues: `{daily_summary['missed_issue_count']}`",
            f"- False positives: `{daily_summary['false_positive_count']}`",
            "",
            *self._render_issue_period_summary(recent_summary),
            "",
            *self._render_issue_period_summary(all_time_summary),
        ]
        return "\n".join(lines) + "\n"

    def render_slack_text(
        self,
        daily_summary: dict[str, Any],
        recent_summary: dict[str, Any],
        all_time_summary: dict[str, Any],
    ) -> str:
        """Render a plain text Slack message from aggregate summaries.

        Args:
            daily_summary: Daily summary dict such as ``{"date": "2026-04-16"}``.
            recent_summary: Rolling-period summary such as ``{"label": "Last 7 days"}``.
            all_time_summary: All-time summary such as ``{"label": "All-time"}``.

        Returns:
            Slack message text such as ``"AI Review Daily Summary - 2026-04-16\n..."``.
        """
        lines = [
            f"AI Review Daily Summary - {daily_summary['date']}",
            f"Repo: {daily_summary['repo']}",
            "",
            "Daily",
            f"Review runs: {daily_summary['review_runs']}",
            f"Evaluated: {daily_summary['evaluated_runs']} / Excluded: {daily_summary['excluded_runs']}",
            f"Mergeable precision: {daily_summary['mergeable']['precision']:.0%} ({daily_summary['mergeable']['success']}/{daily_summary['mergeable']['total']})",
            f"Human-review precision: {daily_summary['human_review']['precision']:.0%} ({daily_summary['human_review']['success']}/{daily_summary['human_review']['total']})",
            f"Missed issues: {daily_summary['missed_issue_count']}",
            f"False positives: {daily_summary['false_positive_count']}",
            "",
            *self._render_slack_period_summary(recent_summary),
            "",
            *self._render_slack_period_summary(all_time_summary),
        ]
        return "\n".join(lines)

    def _render_issue_period_summary(self, summary: dict[str, Any]) -> list[str]:
        lines = [f"## {summary['label']} Summary"]
        if summary.get("start_date") and summary.get("end_date"):
            lines.append(
                f"- Period: `{summary['start_date']}` - `{summary['end_date']}`"
            )
        lines.extend(
            [
                f"- Review runs: `{summary['review_runs']}`",
                f"- Evaluated: `{summary['evaluated_runs']}`",
                f"- Excluded: `{summary['excluded_runs']}`",
                f"- Mergeable: `{summary['mergeable']['success']}/{summary['mergeable']['total']}` ({summary['mergeable']['precision']:.2%})",
                f"- Human review: `{summary['human_review']['success']}/{summary['human_review']['total']}` ({summary['human_review']['precision']:.2%})",
                f"- Missed issues: `{summary['missed_issue_count']}`",
                f"- False positives: `{summary['false_positive_count']}`",
            ]
        )
        return lines

    def _render_slack_period_summary(self, summary: dict[str, Any]) -> list[str]:
        heading = summary["label"]
        if summary.get("start_date") and summary.get("end_date"):
            heading = f"{heading}: {summary['start_date']} - {summary['end_date']}"
        return [
            heading,
            f"Review runs: {summary['review_runs']}",
            f"Evaluated: {summary['evaluated_runs']} / Excluded: {summary['excluded_runs']}",
            f"Mergeable precision: {summary['mergeable']['precision']:.0%} ({summary['mergeable']['success']}/{summary['mergeable']['total']})",
            f"Human-review precision: {summary['human_review']['precision']:.0%} ({summary['human_review']['success']}/{summary['human_review']['total']})",
        ]
