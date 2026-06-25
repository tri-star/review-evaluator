from __future__ import annotations

from io import BytesIO
import urllib.error

import pytest

from infrastructures.github_app_client import GitHubApiError, GitHubAppClient


def test_fetch_collaborator_permission_returns_none_for_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubAppClient(app_id="123", private_key="private-key")
    monkeypatch.setattr(client, "_installation_token", lambda installation_id: "token")

    def request_json(*args: object, **kwargs: object) -> dict[str, object]:
        raise GitHubApiError(status=404, message="not found")

    monkeypatch.setattr(client, "_request_json", request_json)

    assert (
        client.fetch_collaborator_permission(
            repo="owner/repo", username="outside-user", installation_id=1
        )
        == "none"
    )


def test_fetch_collaborator_permission_reraises_non_404_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubAppClient(app_id="123", private_key="private-key")
    monkeypatch.setattr(client, "_installation_token", lambda installation_id: "token")

    def request_json(*args: object, **kwargs: object) -> dict[str, object]:
        raise GitHubApiError(status=500, message="server error")

    monkeypatch.setattr(client, "_request_json", request_json)

    with pytest.raises(GitHubApiError) as error:
        client.fetch_collaborator_permission(
            repo="owner/repo", username="alice", installation_id=1
        )

    assert error.value.status == 500


def test_fetch_pr_issue_comments_follows_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubAppClient(app_id="123", private_key="private-key")
    monkeypatch.setattr(client, "_installation_token", lambda installation_id: "token")

    requested_paths: list[str] = []
    pages = {1: [{"body": f"c{i}"} for i in range(100)], 2: [{"body": "c100"}]}

    def request_json(method: str, path: str, **kwargs: object) -> list[dict[str, str]]:
        requested_paths.append(path)
        page = 2 if "page=2" in path else 1
        return pages[page]

    monkeypatch.setattr(client, "_request_json", request_json)

    comments = client.fetch_pr_issue_comments(
        repo="owner/repo", pr_number=1, installation_id=1
    )

    # 1ページ目がper_page到達のため2ページ目まで取得し、満たない時点で停止する。
    assert len(comments) == 101
    assert requested_paths == [
        "/repos/owner/repo/issues/1/comments?per_page=100&page=1",
        "/repos/owner/repo/issues/1/comments?per_page=100&page=2",
    ]


def test_request_json_wraps_url_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubAppClient(app_id="123", private_key="private-key")

    def urlopen(*args: object, **kwargs: object) -> object:
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    with pytest.raises(GitHubApiError) as error:
        client._request_json(
            "GET",
            "/repos/owner/repo",
            token="token",
            expected_statuses={200},
        )

    assert error.value.status == 502
    assert "timed out" in str(error.value)


def test_request_json_includes_response_body_in_unexpected_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubAppClient(app_id="123", private_key="private-key")

    def urlopen(*args: object, **kwargs: object) -> object:
        raise urllib.error.HTTPError(
            url="https://api.github.com/repos/owner/repo",
            code=422,
            msg="Unprocessable Entity",
            hdrs={},
            fp=BytesIO(b'{"message":"Validation Failed"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    with pytest.raises(GitHubApiError) as error:
        client._request_json(
            "POST",
            "/repos/owner/repo/actions/workflows/pr-ai-review.yml/dispatches",
            token="token",
            expected_statuses={204},
            payload={"ref": "main"},
        )

    assert error.value.status == 422
    assert "Validation Failed" in str(error.value)
