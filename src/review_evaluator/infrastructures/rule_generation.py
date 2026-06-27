from __future__ import annotations

from typing import Any


# 生成器が返すルール判定の JSON スキーマ。構造化出力で最初の text ブロック / message が
# このスキーマに沿った JSON になることを保証し、urllib でも安全に json.loads できる。
# action のみ必須・他は任意とし、最終的な妥当性は RuleExtractionService 側で検証する。
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


def build_user_content(
    *,
    comments: list[dict[str, Any]],
    existing_rules: list[dict[str, Any]],
) -> str:
    """Render the user message shared by both rule generators.

    Args:
        comments: Candidate review comments such as ``[{"body": "...", "path": "src/foo.ts"}]``.
        existing_rules: Currently stored rules used for de-duplication.

    Returns:
        A prompt string embedding the existing rules and the candidate comments.
    """
    import json

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
