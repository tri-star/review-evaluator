from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from typing import Any

import pytest

from infrastructures.openai_rule_generator import OpenAIRuleGenerator


def _chat_response(
    decisions: list[dict[str, Any]] | None = None, refusal: str | None = None
) -> bytes:
    message: dict[str, Any] = {}
    if refusal is not None:
        message["refusal"] = refusal
    else:
        message["content"] = json.dumps({"decisions": decisions or []})
    return json.dumps({"choices": [{"message": message}]}).encode("utf-8")


def test_extract_rules_parses_decisions_from_message_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def urlopen(request: Any, timeout: int = 0) -> Any:
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.headers["Authorization"]
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
        return _FakeResponse(_chat_response(decisions))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    generator = OpenAIRuleGenerator(api_key="sk-test", model="gpt-5.4-mini")
    result = generator.extract_rules(
        comments=[{"body": "Service層へ移してください", "path": "src/api.ts"}],
        existing_rules=[{"rule_id": "existing-1", "name": "x/y"}],
    )

    assert result[0]["name"] == "controller/layer-violation"
    assert result[1] == {"action": "reuse", "rule_id": "existing-1"}
    assert captured["authorization"] == "Bearer sk-test"
    assert captured["payload"]["model"] == "gpt-5.4-mini"
    assert captured["payload"]["response_format"]["type"] == "json_schema"


def test_extract_rules_returns_empty_on_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(request: Any, timeout: int = 0) -> Any:
        return _FakeResponse(_chat_response(refusal="I can't help with that."))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    generator = OpenAIRuleGenerator(api_key="sk-test")
    result = generator.extract_rules(comments=[{"body": "x"}], existing_rules=[])

    assert result == []


def test_extract_rules_returns_empty_when_no_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(request: Any, timeout: int = 0) -> Any:
        return _FakeResponse(json.dumps({"choices": []}).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    generator = OpenAIRuleGenerator(api_key="sk-test")
    assert generator.extract_rules(comments=[{"body": "x"}], existing_rules=[]) == []


def test_extract_rules_returns_empty_on_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(request: Any, timeout: int = 0) -> Any:
        truncated_content = '{"decisions": [{"action":'
        body = json.dumps(
            {"choices": [{"message": {"content": truncated_content}}]}
        ).encode("utf-8")
        return _FakeResponse(body)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    generator = OpenAIRuleGenerator(api_key="sk-test")
    result = generator.extract_rules(comments=[{"body": "x"}], existing_rules=[])

    assert result == []


def test_request_raises_runtime_error_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(request: Any, timeout: int = 0) -> Any:
        raise urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b'{"error": {"message": "Invalid API key"}}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    generator = OpenAIRuleGenerator(api_key="sk-bad")
    with pytest.raises(RuntimeError, match="401"):
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
