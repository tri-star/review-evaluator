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
