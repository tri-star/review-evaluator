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


OPENAI_API = "https://api.openai.com"
DEFAULT_MODEL = "gpt-5.4-mini"


class OpenAIRuleGenerator:
    """LLM-backed rule classifier/generator using the OpenAI Chat Completions API."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        api_base: str = OPENAI_API,
    ) -> None:
        """Initialize the generator.

        Args:
            api_key: OpenAI API key such as ``"sk-..."``.
            model: Model id override. Defaults to ``OPENAI_MODEL`` env or ``gpt-5.4-mini``.
            api_base: API base URL, overridable for tests.

        Returns:
            None.
        """
        self.api_key = api_key
        self.model = model or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
        self.api_base = api_base

    def extract_rules(
        self,
        *,
        comments: list[dict[str, Any]],
        existing_rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Classify candidate comments into rule decisions via OpenAI.

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
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "rule_decisions",
                    "schema": DECISIONS_SCHEMA,
                    "strict": False,
                },
            },
        }
        response = self._request(payload)
        return self._parse_decisions(response)

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_base}/v1/chat/completions",
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            },
        )
        logger.debug("OpenAI API request", extra={"model": self.model})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8")
            logger.warning(
                "OpenAI API error",
                extra={"status": error.code, "detail": detail[:500]},
            )
            raise
        except urllib.error.URLError as error:
            logger.warning(
                "OpenAI API network error", extra={"reason": str(error.reason)}
            )
            raise
        return json.loads(body)

    def _parse_decisions(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract the decisions list from a Chat Completions response.

        Args:
            response: Parsed Chat Completions response body.

        Returns:
            The ``decisions`` list, or ``[]`` when the model produced none.
        """
        choices = response.get("choices") or []
        if not choices:
            return []
        message = choices[0].get("message") or {}
        if message.get("refusal"):
            logger.warning("OpenAI API refused rule extraction")
            return []
        content = message.get("content") or ""
        if not content:
            return []
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("OpenAI API returned invalid JSON; skipping")
            return []
        decisions = parsed.get("decisions")
        return decisions if isinstance(decisions, list) else []
