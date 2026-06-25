from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from observability import logger


ANTHROPIC_API = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-opus-4-8"

# 生成器が返すルール判定の JSON スキーマ。構造化出力で最初の text ブロックが
# このスキーマに沿った JSON になることを保証し、urllib でも安全に json.loads できる。
DECISIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "reuse"]},
                    "rule_id": {"type": "string"},
                    "name": {"type": "string"},
                    "package": {"type": "string", "enum": ["frontend", "backend"]},
                    "category": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
あなたはコードレビューのナレッジを蓄積するアシスタントです。
人間のレビュアーが残したPRコメント群を読み、再利用可能な「レビュールール」を抽出します。

判定ルール:
- 「ありがとうございます」「LGTM」など、レビュー観点を含まない雑談・相槌は無視し、decisionsに含めない。
- 既存ルール一覧で既に表現済みの指摘は、新規作成せず {"action": "reuse", "rule_id": "<該当ID>"} を返す。
- 新しいレビュー観点のみ {"action": "create", ...} を返す。createでは以下を生成する:
  - name: kebab-case を "/" で繋いだ識別名 (例 "controller/layer-violation", "design/file-name-convention")
  - package: "frontend" または "backend" (コメントやpathから判断)
  - category: "security" / "code-quality" / "performance" など
  - body: ルールの内容を日本語で簡潔に記述 (複数行可)
- 同じ観点のコメントが複数あっても、ルールは1件にまとめる。
"""


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
            model: Model id override. Defaults to ``ANTHROPIC_MODEL`` env or ``claude-opus-4-8``.
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
        user_content = self._build_user_content(
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

    def _build_user_content(
        self,
        *,
        comments: list[dict[str, Any]],
        existing_rules: list[dict[str, Any]],
    ) -> str:
        existing_view = [
            {
                "rule_id": rule.get("rule_id"),
                "name": rule.get("name"),
                "package": rule.get("package"),
                "category": rule.get("category"),
                "body": rule.get("body"),
            }
            for rule in existing_rules
        ]
        return (
            "# 既存ルール一覧 (重複判定に使用)\n"
            f"{json.dumps(existing_view, ensure_ascii=False, indent=2)}\n\n"
            "# レビューコメント候補\n"
            f"{json.dumps(comments, ensure_ascii=False, indent=2)}\n\n"
            "上記コメントを判定し、decisions を返してください。"
        )

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
            raise
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
        parsed = json.loads(text)
        decisions = parsed.get("decisions")
        return decisions if isinstance(decisions, list) else []
