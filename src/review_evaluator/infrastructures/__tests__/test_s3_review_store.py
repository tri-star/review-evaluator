from __future__ import annotations

import io
from datetime import date
from typing import Any

import pytest

from infrastructures.s3_review_store import S3ReviewStore


class FakePaginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.last_prefix: str | None = None
        self.prefixes: list[str] = []

    def paginate(self, Bucket: str, Prefix: str) -> list[dict[str, Any]]:
        self.last_prefix = Prefix
        self.prefixes.append(Prefix)
        return self.pages


class FakeS3Client:
    def __init__(self, objects: dict[str, str], pages: list[dict[str, Any]]) -> None:
        self.objects = objects
        self.paginator = FakePaginator(pages=pages)
        self.put_calls: list[dict[str, Any]] = []

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_objects_v2"
        return self.paginator

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": io.BytesIO(self.objects[Key].encode("utf-8"))}

    def put_object(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)


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
            "run_at": "2026-04-20T14:32:22+00:00",
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
        "run_at": "2026-04-20T14:32:22+00:00",
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


def test_reviews_json_lines形式を複数行と空行込みで読める() -> None:
    key = (
        "reviews/repo_partition=tri-star_tasche/year=2026/month=04/day=20/"
        "pr=13/run=2026-04-20T14-32-22Z.json"
    )
    s3_client = FakeS3Client(
        objects={
            key: (
                '{"verdict": "human-review"}\n'
                "\n"
                '{"verdict": "mergeable", "run_at": "2026-04-20T15:00:00Z"}\n'
            )
        },
        pages=[{"Contents": [{"Key": key}]}],
    )
    store = S3ReviewStore(s3_client=s3_client, bucket="bucket")

    result = store.load_review_results(repo="tri-star/tasche", target_date="2026-04-20")

    assert result == [
        {
            "repo": "tri-star/tasche",
            "pr_number": 13,
            "run_at": "2026-04-20T14:32:22+00:00",
            "verdict": "human-review",
        },
        {
            "repo": "tri-star/tasche",
            "pr_number": 13,
            "run_at": "2026-04-20T15:00:00Z",
            "verdict": "mergeable",
        },
    ]


def test_evaluation書込時に_repo_partition_配下へ保存する() -> None:
    s3_client = FakeS3Client(objects={}, pages=[])
    store = S3ReviewStore(s3_client=s3_client, bucket="bucket")

    store.write_evaluation(
        {
            "repo": "tri-star/tasche",
            "pr_number": 13,
            "evaluated_at": "2026-04-21T01:02:03+00:00",
            "evaluation_status": "success",
        }
    )

    assert s3_client.put_calls[0]["Key"] == (
        "evaluations/repo_partition=tri-star_tasche/year=2026/month=04/day=21/"
        "pr=13.json"
    )


def test_週次evaluation読込時に_repo_partition_配下を辿る() -> None:
    s3_client = FakeS3Client(objects={}, pages=[])
    store = S3ReviewStore(s3_client=s3_client, bucket="bucket")

    store.load_weekly_evaluations(repo="tri-star/tasche", end_date=date(2026, 4, 21))

    assert s3_client.paginator.last_prefix == (
        "evaluations/repo_partition=tri-star_tasche/year=2026/month=04/day=15/"
    )


def test_直近evaluation読込時に指定日数分の_prefix_を辿る() -> None:
    s3_client = FakeS3Client(objects={}, pages=[])
    store = S3ReviewStore(s3_client=s3_client, bucket="bucket")

    store.load_recent_evaluations(
        repo="tri-star/tasche", end_date=date(2026, 4, 21), days=3
    )

    assert s3_client.paginator.prefixes == [
        "evaluations/repo_partition=tri-star_tasche/year=2026/month=04/day=21/",
        "evaluations/repo_partition=tri-star_tasche/year=2026/month=04/day=20/",
        "evaluations/repo_partition=tri-star_tasche/year=2026/month=04/day=19/",
    ]


def test_直近evaluation読込時に_days_が1未満なら失敗する() -> None:
    s3_client = FakeS3Client(objects={}, pages=[])
    store = S3ReviewStore(s3_client=s3_client, bucket="bucket")

    with pytest.raises(ValueError, match="days"):
        store.load_recent_evaluations(
            repo="tri-star/tasche", end_date=date(2026, 4, 21), days=0
        )


def test_通算daily_summary読込時に_repo_partition_全体を辿る() -> None:
    key = "aggregates/daily/repo_partition=tri-star_tasche/date=2026-04-21/summary.json"
    s3_client = FakeS3Client(
        objects={key: '{"repo": "tri-star/tasche", "date": "2026-04-21"}'},
        pages=[{"Contents": [{"Key": key}]}],
    )
    store = S3ReviewStore(s3_client=s3_client, bucket="bucket")

    result = store.load_all_daily_summaries(repo="tri-star/tasche")

    assert (
        s3_client.paginator.last_prefix
        == "aggregates/daily/repo_partition=tri-star_tasche/"
    )
    assert result == [
        {
            "repo": "tri-star/tasche",
            "date": "2026-04-21",
            "s3_key": key,
        }
    ]


def test_summary書込時に_repo_partition_配下へ保存する() -> None:
    s3_client = FakeS3Client(objects={}, pages=[])
    store = S3ReviewStore(s3_client=s3_client, bucket="bucket")

    store.write_summary(
        summary={"repo": "tri-star/tasche", "date": "2026-04-21"},
        period="daily",
        key_name="2026-04-21",
    )
    store.write_summary(
        summary={"repo": "tri-star/tasche", "week": "2026-W17"},
        period="weekly",
        key_name="2026-W17",
    )

    assert s3_client.put_calls[0]["Key"] == (
        "aggregates/daily/repo_partition=tri-star_tasche/date=2026-04-21/summary.json"
    )
    assert s3_client.put_calls[1]["Key"] == (
        "aggregates/weekly/repo_partition=tri-star_tasche/week=2026-W17/summary.json"
    )
