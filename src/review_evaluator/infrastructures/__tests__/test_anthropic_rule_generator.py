from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from typing import Any

import pytest

from infrastructures.anthropic_rule_generator import AnthropicRuleGenerator


def _message_response(
    decisions: list[dict[str, Any]], stop_reason: str = "end_turn"
) -> bytes:
    body = {
        "stop_reason": stop_reason,
        "content": [{"type": "text", "text": json.dumps({"decisions": decisions})}],
    }
    return json.dumps(body).encode("utf-8")


def test_extract_rules_parses_decisions_from_text_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def urlopen(request: Any, timeout: int = 0) -> Any:
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["api_key"] = request.headers["X-api-key"]
        decisions = [
            {
                "action": "create",
                "name": "controller/layer-violation",
                "package": "backend",
                "category": "code-quality",
                "body": "Controller層にロジックを書かない。",
            },
            {"action": "reuse", "rule_id": "existing-1"},
        ]
        return _FakeResponse(_message_response(decisions))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    generator = AnthropicRuleGenerator(api_key="sk-test", model="claude-opus-4-8")
    result = generator.extract_rules(
        comments=[{"body": "Service層へ移してください", "path": "src/api.ts"}],
        existing_rules=[{"rule_id": "existing-1", "name": "x/y"}],
    )

    assert result[0]["name"] == "controller/layer-violation"
    assert result[1] == {"action": "reuse", "rule_id": "existing-1"}
    # 構造化出力スキーマを指定して送っていることを確認。
    assert captured["payload"]["output_config"]["format"]["type"] == "json_schema"
    assert captured["payload"]["model"] == "claude-opus-4-8"


def test_extract_rules_returns_empty_on_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(request: Any, timeout: int = 0) -> Any:
        body = json.dumps({"stop_reason": "refusal", "content": []}).encode("utf-8")
        return _FakeResponse(body)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    generator = AnthropicRuleGenerator(api_key="sk-test")
    result = generator.extract_rules(comments=[{"body": "x"}], existing_rules=[])

    assert result == []


def test_extract_rules_returns_empty_on_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(request: Any, timeout: int = 0) -> Any:
        body = json.dumps(
            {
                "stop_reason": "max_tokens",
                "content": [{"type": "text", "text": '{"decisions": [{"action":'}],
            }
        ).encode("utf-8")
        return _FakeResponse(body)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    generator = AnthropicRuleGenerator(api_key="sk-test")
    result = generator.extract_rules(comments=[{"body": "x"}], existing_rules=[])

    assert result == []


def test_request_raises_runtime_error_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(request: Any, timeout: int = 0) -> Any:
        raise urllib.error.HTTPError(
            url="https://api.anthropic.com/v1/messages",
            code=429,
            msg="Too Many Requests",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b'{"error": {"type": "rate_limit_error"}}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    generator = AnthropicRuleGenerator(api_key="sk-test")
    with pytest.raises(RuntimeError, match="429"):
        generator.extract_rules(comments=[{"body": "x"}], existing_rules=[])


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._buffer = BytesIO(body)

    def read(self) -> bytes:
        return self._buffer.read()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None
