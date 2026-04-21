from __future__ import annotations

import json
import urllib.request


class SlackNotifier:
    """Send daily and weekly summaries to Slack."""

    def post_summary(self, webhook_url: str, text: str) -> None:
        """Post daily and optional weekly summaries to Slack.

        Args:
            webhook_url: Slack Incoming Webhook URL such as ``"https://hooks.slack.com/services/..."``.
            text: Slack message text such as ``"AI Review Daily Summary - 2026-04-16\n..."``.

        Returns:
            None. A message is posted to Slack.
        """
        request = urllib.request.Request(
            webhook_url,
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"text": text}).encode("utf-8"),
        )
        with urllib.request.urlopen(request, timeout=20):
            return
