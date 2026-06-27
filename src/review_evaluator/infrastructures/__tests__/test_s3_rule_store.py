from __future__ import annotations

import io
import json
from typing import Any

from botocore.exceptions import ClientError
from infrastructures.s3_rule_store import S3RuleStore


class FakePaginator:
    def __init__(self, objects: dict[str, str]) -> None:
        self.objects = objects

    def paginate(self, Bucket: str, Prefix: str) -> list[dict[str, Any]]:
        contents = [
            {"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)
        ]
        return [{"Contents": contents}]


class FakeS3Client:
    """In-memory S3 client whose contents update on put/delete."""

    def __init__(self, objects: dict[str, str] | None = None) -> None:
        self.objects = dict(objects or {})
        self.deleted: list[str] = []

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_objects_v2"
        return FakePaginator(self.objects)

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": io.BytesIO(self.objects[Key].encode("utf-8"))}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **_: Any) -> None:
        self.objects[Key] = Body.decode("utf-8")

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append(Key)
        self.objects.pop(Key, None)

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
            )
        return {}


def test_save_rule_は_package_配下に_rule_id_でjson保存する() -> None:
    s3_client = FakeS3Client()
    store = S3RuleStore(s3_client=s3_client, bucket="bucket")

    store.save_rule(
        {
            "rule_id": "abc-123",
            "name": "controller/layer-violation",
            "package": "backend",
            "category": "code-quality",
            "body": "Controller層にロジックを書かない。",
            "recent_usage": [],
        }
    )

    key = "rules/package=backend/abc-123.json"
    assert key in s3_client.objects
    assert json.loads(s3_client.objects[key])["name"] == "controller/layer-violation"


def test_list_rules_は全パッケージのルールを読み込む() -> None:
    s3_client = FakeS3Client(
        objects={
            "rules/package=backend/r1.json": json.dumps({"rule_id": "r1"}),
            "rules/package=frontend/r2.json": json.dumps({"rule_id": "r2"}),
            "rules/package=backend/_index.txt": "ignored",
        }
    )
    store = S3RuleStore(s3_client=s3_client, bucket="bucket")

    rules = store.list_rules()

    assert sorted(rule["rule_id"] for rule in rules) == ["r1", "r2"]


def test_append_usage_は新しい順に件数を上限で保持する() -> None:
    rule = {"rule_id": "r1", "package": "backend", "recent_usage": ["t0"]}
    s3_client = FakeS3Client(
        objects={"rules/package=backend/r1.json": json.dumps(rule)}
    )
    store = S3RuleStore(s3_client=s3_client, bucket="bucket")

    store.append_usage(rule_id="r1", used_at="t1")

    saved = json.loads(s3_client.objects["rules/package=backend/r1.json"])
    assert saved["recent_usage"] == ["t0", "t1"]


def test_append_usage_は未知の_rule_id_を無視する() -> None:
    s3_client = FakeS3Client()
    store = S3RuleStore(s3_client=s3_client, bucket="bucket")

    store.append_usage(rule_id="missing", used_at="t1")

    assert s3_client.objects == {}


def test_delete_rule_は対象キーを削除する() -> None:
    s3_client = FakeS3Client(
        objects={"rules/package=frontend/r9.json": json.dumps({"rule_id": "r9"})}
    )
    store = S3RuleStore(s3_client=s3_client, bucket="bucket")

    store.delete_rule(rule_id="r9")

    assert s3_client.deleted == ["rules/package=frontend/r9.json"]
    assert s3_client.objects == {}


def test_delete_rule_with_package_skips_prefix_scan() -> None:
    """package 指定時は list_objects_v2 を呼ばずに直接 delete_object する。"""
    scan_calls: list[str] = []

    class TrackingScanClient(FakeS3Client):
        def get_paginator(self, name: str) -> FakePaginator:
            scan_calls.append(name)
            return super().get_paginator(name)

    s3_client = TrackingScanClient(
        objects={"rules/package=backend/r10.json": json.dumps({"rule_id": "r10"})}
    )
    store = S3RuleStore(s3_client=s3_client, bucket="bucket")

    store.delete_rule(rule_id="r10", package="backend")

    assert scan_calls == []
    assert s3_client.deleted == ["rules/package=backend/r10.json"]


def test_find_rule_key_uses_head_object_not_scan() -> None:
    """_find_rule_key は list_objects_v2 スキャンを行わず head_object を使う。"""
    scan_calls: list[str] = []

    class TrackingScanClient(FakeS3Client):
        def get_paginator(self, name: str) -> FakePaginator:
            scan_calls.append(name)
            return super().get_paginator(name)

    s3_client = TrackingScanClient(
        objects={
            "rules/package=backend/r11.json": json.dumps(
                {"rule_id": "r11", "package": "backend", "recent_usage": []}
            )
        }
    )
    store = S3RuleStore(s3_client=s3_client, bucket="bucket")

    store.append_usage(rule_id="r11", used_at="t1")

    assert scan_calls == []
    saved = json.loads(s3_client.objects["rules/package=backend/r11.json"])
    assert saved["recent_usage"] == ["t1"]
