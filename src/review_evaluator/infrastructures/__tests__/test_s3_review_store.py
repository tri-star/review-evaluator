from __future__ import annotations

import io
from typing import Any

from infrastructures.s3_review_store import S3ReviewStore


class FakePaginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.last_prefix: str | None = None

    def paginate(self, Bucket: str, Prefix: str) -> list[dict[str, Any]]:
        self.last_prefix = Prefix
        return self.pages


class FakeS3Client:
    def __init__(self, objects: dict[str, str], pages: list[dict[str, Any]]) -> None:
        self.objects = objects
        self.paginator = FakePaginator(pages=pages)

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_objects_v2"
        return self.paginator

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": io.BytesIO(self.objects[Key].encode("utf-8"))}


def test_reviews_読込時に_s3_key_から不足項目を補完できる() -> None:
    key = (
        "reviews/repo_partition=tri-star_tasche/year=2026/month=04/day=20/"
        "pr=13/run=2026-04-20T14-32-22Z.json"
    )
    s3_client = FakeS3Client(
        objects={key: '{"verdict": "human-review", "confidence": 0.99, "reasons": []}'},
        pages=[{"Contents": [{"Key": key}]}],
    )
    store = S3ReviewStore(s3_client=s3_client, bucket="bucket")

    result = store.load_review_results(repo="tri-star/tasche", target_date="2026-04-20")

    assert result == [
        {
            "repo": "tri-star/tasche",
            "pr_number": 13,
            "run_at": "2026-04-20T14-32-22+00:00",
            "verdict": "human-review",
            "confidence": 0.99,
            "reasons": [],
        }
    ]


def test_s3_key正規化ヘルパーが_repo_pr_run_at_を補完できる() -> None:
    store = S3ReviewStore(s3_client=object(), bucket="bucket")

    result = store._normalize_review_item(
        {
            "s3_key": (
                "reviews/repo_partition=tri-star_tasche/year=2026/month=04/day=20/"
                "pr=13/run=2026-04-20T14-32-22Z.json"
            ),
            "verdict": "human-review",
        }
    )

    assert result == {
        "repo": "tri-star/tasche",
        "pr_number": 13,
        "run_at": "2026-04-20T14-32-22+00:00",
        "verdict": "human-review",
    }


def test_reviews_json内に既存値があればそれを優先する() -> None:
    key = (
        "reviews/repo_partition=tri-star_tasche/year=2026/month=04/day=20/"
        "pr=13/run=2026-04-20T14-32-22Z.json"
    )
    s3_client = FakeS3Client(
        objects={
            key: (
                '{"repo": "custom/repo", "pr_number": 99, '
                '"run_at": "2026-04-20T14:32:22Z", "verdict": "mergeable"}'
            )
        },
        pages=[{"Contents": [{"Key": key}]}],
    )
    store = S3ReviewStore(s3_client=s3_client, bucket="bucket")

    result = store.load_review_results(repo="tri-star/tasche", target_date="2026-04-20")

    assert result == [
        {
            "repo": "custom/repo",
            "pr_number": 99,
            "run_at": "2026-04-20T14:32:22Z",
            "verdict": "mergeable",
        }
    ]
