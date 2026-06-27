from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from infrastructures.rule_generation import (
    DECISIONS_SCHEMA,
    SYSTEM_PROMPT,
    build_user_content,
)
from observability import logger


ANTHROPIC_API = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5"


class AnthropicRuleGenerator:
    """LLM-backed rule classifier/generator using the Claude Messages API."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        api_base: str = ANTHROPIC_API,
    ) -> None:
        """Initialize the generator.

        Args:
            api_key: Anthropic API key such as ``"sk-ant-..."``.
            model: Model id override. Defaults to ``ANTHROPIC_MODEL`` env or ``claude-haiku-4-5``.
            api_base: API base URL, overridable for tests.

        Returns:
            None.
        """
        self.api_key = api_key
        self.model = model or os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL
        self.api_base = api_base

    def extract_rules(
        self,
        *,
        comments: list[dict[str, Any]],
        existing_rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Classify candidate comments into rule decisions via Claude.

        Args:
            comments: Candidate review comments such as ``[{"body": "...", "path": "src/foo.ts"}]``.
            existing_rules: Currently stored rules used for de-duplication.

        Returns:
            Decisions such as ``[{"action": "create", "name": "...", ...}]``.
        """
        user_content = build_user_content(
            comments=comments, existing_rules=existing_rules
        )
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "output_config": {
                "format": {"type": "json_schema", "schema": DECISIONS_SCHEMA}
            },
            "messages": [{"role": "user", "content": user_content}],
        }
        response = self._request(payload)
        return self._parse_decisions(response)

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_base}/v1/messages",
            data=data,
            method="POST",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )
        logger.debug("Anthropic API request", extra={"model": self.model})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8")
            logger.warning(
                "Anthropic API error",
                extra={"status": error.code, "detail": detail[:500]},
            )
            raise RuntimeError(f"{error.code}: {detail[:500]}") from error
        except urllib.error.URLError as error:
            logger.warning(
                "Anthropic API network error", extra={"reason": str(error.reason)}
            )
            raise
        return json.loads(body)

    def _parse_decisions(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract the decisions list from a Messages API response.

        Args:
            response: Parsed Messages API response body.

        Returns:
            The ``decisions`` list, or ``[]`` when the model produced none.
        """
        stop_reason = response.get("stop_reason")
        if stop_reason == "refusal":
            logger.warning("Anthropic API refused rule extraction")
            return []

        text = next(
            (
                block.get("text", "")
                for block in response.get("content", [])
                if block.get("type") == "text"
            ),
            "",
        )
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Anthropic API returned invalid JSON; skipping")
            return []
        decisions = parsed.get("decisions")
        return decisions if isinstance(decisions, list) else []
