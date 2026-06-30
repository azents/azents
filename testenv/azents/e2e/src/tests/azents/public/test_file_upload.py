"""file upload/Exchange file API E2E test.

file upload, Exchange file list, download/delete t verifyt.
"""

import json
import time

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.chat_v1_api import ChatV1Api
from pydantic import TypeAdapter, ValidationError
from websockets.sync.client import connect as ws_connect
from websockets.sync.connection import Connection

from support.utils import (
    PNG_1X1,
    create_chat_session,
    create_chat_session_with_agent,
    create_second_user_token,
    unique,
    upload_file,
)

_UPLOAD_PROMPT = "Describe uploaded image and file"
_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


def _exchange_uri_is_file_location(uri: object) -> bool:
    """Exchange URIt opaque file-locationt verifyt."""
    return (
        isinstance(uri, str)
        and uri.startswith("exchange://")
        and not uri.startswith("exchange://files/")
    )


def _headers(token: str) -> dict[str, str]:
    """Bearer auth header t t."""
    return {"Authorization": f"Bearer {token}"}


def _ws_url(http_url: str) -> str:
    """HTTP URL t WebSocket URL t t."""
    if http_url.startswith("http://"):
        return "ws://" + http_url.removeprefix("http://")
    if http_url.startswith("https://"):
        return "wss://" + http_url.removeprefix("https://")
    return http_url


def _issue_ticket(
    public_api_client: azentspublicclient.ApiClient,
    access_token: str,
) -> str:
    """WebSocket ticket t t."""
    return (
        ChatV1Api(public_api_client)
        .chat_v1_issue_ws_ticket(_headers=_headers(access_token))
        .ticket
    )


def _connect_existing_chat(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    access_token: str,
    session_id: str,
) -> Connection:
    """t chat session WebSocket t connectiont."""
    ticket = _issue_ticket(public_api_client, access_token)
    ws_uri = f"{_ws_url(public_url)}/chat/v1/sessions/{session_id}?ticket={ticket}"
    return ws_connect(ws_uri)


def _recv_event(ws: Connection, *, timeout: float = 10) -> dict[str, object]:
    """WebSocket event t JSON object t t."""
    raw = ws.recv(timeout=timeout)
    return _object_item(json.loads(raw), label="WebSocket payload")


def _object_item(raw_item: object, *, label: str) -> dict[str, object]:
    """JSON object t verifyt returnt."""
    try:
        return _JSON_OBJECT.validate_python(raw_item)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {raw_item!r}") from exc


def _object_items(raw_items: object, *, label: str) -> list[dict[str, object]]:
    """JSON list[object] t verifyt returnt."""
    try:
        return _JSON_OBJECT_LIST.validate_python(raw_items)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object list: {raw_items!r}") from exc


def _wait_for_user_input(
    ws: Connection,
    content: str,
    *,
    timeout: float = 90,
) -> dict[str, object]:
    """t content t durable event user_message event t t."""
    deadline = time.monotonic() + timeout
    observed: list[object] = []
    while time.monotonic() < deadline:
        try:
            event = _recv_event(ws, timeout=5)
        except TimeoutError:
            continue
        observed.append(event.get("kind") or event.get("type"))
        if event.get("type") == "history_event_appended":
            event = _object_item(
                event.get("event"),
                label="history_event_appended event",
            )
        if event.get("kind") != "user_message":
            continue
        payload = _object_item(
            event.get("payload"),
            label="user_message payload",
        )
        if _content_text(payload.get("content")) == content:
            return payload
    raise TimeoutError(f"user_input was not observed: {content}, {observed}")


def _content_text(content: object) -> str:
    """event content string t part arrayt text bodyt returnt."""
    if isinstance(content, str):
        return content
    try:
        parts = _JSON_OBJECT_LIST.validate_python(content)
    except ValidationError:
        return ""
    texts: list[str] = []
    for part in parts:
        part_type = part.get("type")
        text = part.get("text")
        if part_type == "input_text" and isinstance(text, str):
            texts.append(text)
    return "\n".join(texts)


def _assert_file_payload_is_blob_free(payload: object, *, label: str) -> None:
    """file payload t raw provider blob t t t verifyt."""
    encoded = json.dumps(payload, ensure_ascii=False)
    forbidden = [
        "file_data",
        "data:image",
        '"base64"',
        '"provider_payload"',
        '"input_file"',
        "exchange://files/",
    ]
    leaked = [marker for marker in forbidden if marker in encoded]
    assert leaked == [], f"{label} leaked raw/legacy file payload markers: {leaked}"


def _mock_openai_journal_payload(mock_openai_url: str) -> object:
    """AIMock journal JSON payload t returnt."""
    return requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()


def _reset_mock_openai(mock_openai_url: str) -> None:
    """AIMock request journal t initializet."""
    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()


def _wait_for_upload_journal(
    mock_openai_url: str,
    timeout: float = 90,
) -> str:
    """AIMock journal t upload t model inputt t t t."""
    deadline = time.monotonic() + timeout
    last_journal = ""
    while time.monotonic() < deadline:
        payload = _mock_openai_journal_payload(mock_openai_url)
        last_journal = json.dumps(payload, ensure_ascii=False)
        has_upload_input = all(
            value in last_journal
            for value in [_UPLOAD_PROMPT, "nul-image.png", "notes.txt"]
        )
        if has_upload_input:
            return last_journal
        time.sleep(0.5)
    raise TimeoutError(
        f"AIMock journal did not include uploaded file and image input: {last_journal}"
    )


def _list_history(
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object]:
    """REST history event page t fetcht."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return _object_item(response.json(), label="list history response")


def _message_items(payload: dict[str, object]) -> list[dict[str, object]]:
    """REST history item listt verifyt returnt."""
    events = _object_items(payload.get("items"), label="REST history items")
    items: list[dict[str, object]] = []
    for event in events:
        if event.get("kind") not in {"user_message", "assistant_message"}:
            continue
        event_payload = _object_item(event.get("payload"), label="history payload")
        items.append(
            {
                "id": event.get("external_id") or event.get("id"),
                "content": _content_text(event_payload.get("content")),
                "attachments": event_payload.get("attachments"),
            }
        )
    return items


def _message_with_content(
    payload: dict[str, object],
    content: str,
) -> dict[str, object]:
    """REST history t t content t t message t t."""
    for item in _message_items(payload):
        if item.get("content") == content:
            return item
    raise AssertionError(f"message content not found: {content}")


def _wait_for_rest_message(
    server_url: str,
    token: str,
    session_id: str,
    content: str,
    *,
    timeout: float = 90,
) -> dict[str, object]:
    """REST history t t content t t t t."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        payload = _list_history(server_url, token, session_id)
        last_payload = payload
        try:
            return _message_with_content(payload, content)
        except AssertionError:
            time.sleep(0.5)
    raise TimeoutError(f"REST message was not observed: {content}, {last_payload!r}")


# ---------------------------------------------------------------------------
# File Upload
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Phase 1 does not include AgentSession-aware chat bootstrap "
        "for file upload e2e."
    )
)
class TestFileUpload:
    """file upload API test."""

    def test_upload_file(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """file upload success t URI, media_type, sizet returnt."""
        token, session_id, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        content = PNG_1X1
        response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
            session_id,
            filename="photo.png",
            content=content,
        )

        assert response.status_code == 200
        body = response.json()
        assert "uri" in body
        assert _exchange_uri_is_file_location(body["uri"])
        assert body["media_type"] == "image/png"
        assert body["size"] == len(content)

    def test_upload_without_auth_returns_401(
        self,
        azents_public_server_url: str,
    ) -> None:
        """auth t upload t 401t returnt."""
        response = requests.post(
            f"{azents_public_server_url}/chat/v1/sessions/{unique()}/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
            timeout=10,
        )
        assert response.status_code == 401

    def test_upload_to_nonexistent_session_returns_404(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """existst t sessiont upload t 404t returnt."""
        token, _, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
            "00000000000000000000000000000000",
            filename="test.txt",
            content=b"hello",
            media_type="text/plain",
        )
        assert response.status_code == 404

    def test_upload_to_other_users_session_returns_403(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """t usert sessiont upload t 403t returnt."""
        _, session_id, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        other_token = create_second_user_token(public_api_client, admin_api_client)

        response = upload_file(
            azents_public_server_url,
            other_token,
            agent_id,
            session_id,
            filename="test.txt",
            content=b"hello",
            media_type="text/plain",
        )
        assert response.status_code == 403

    def test_upload_exceeding_size_limit_returns_413(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """20MB t file upload t 413t returnt."""
        token, session_id, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        # 20MB + 1 byte
        large_content = b"x" * (20 * 1024 * 1024 + 1)
        response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
            session_id,
            filename="large.bin",
            content=large_content,
            media_type="application/octet-stream",
        )
        assert response.status_code == 413


# ---------------------------------------------------------------------------
# Exchange Files
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Phase 1 does not include AgentSession-aware chat bootstrap "
        "for file upload e2e."
    )
)
class TestExchangeFiles:
    """Exchange file API test."""

    def test_list_exchange_files_empty(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """t sessiont t items listt returnt."""
        token, session_id, _ = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        response = requests.get(
            f"{azents_public_server_url}/chat/v1/sessions/{session_id}/exchange-files",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []

    def test_list_exchange_files_without_auth_returns_401(
        self,
        azents_public_server_url: str,
    ) -> None:
        """auth t Exchange file list fetch t 401t returnt."""
        response = requests.get(
            f"{azents_public_server_url}/chat/v1/sessions/{unique()}/exchange-files",
            timeout=10,
        )
        assert response.status_code == 401

    def test_list_exchange_files_other_users_session_returns_403(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """t usert Exchange file list fetch t 403t returnt."""
        _, session_id = create_chat_session(
            public_api_client, admin_api_client, azents_public_server_url
        )

        other_token = create_second_user_token(public_api_client, admin_api_client)

        response = requests.get(
            f"{azents_public_server_url}/chat/v1/sessions/{session_id}/exchange-files",
            headers={"Authorization": f"Bearer {other_token}"},
            timeout=10,
        )
        assert response.status_code == 403

    def test_upload_then_list_exchange_files(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """file upload t Exchange file listt t checkt."""
        token, session_id, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        content = b"hello session data"
        upload_response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
            session_id,
            filename="test.txt",
            content=content,
            media_type="text/plain",
        )
        assert upload_response.status_code == 200

        list_response = requests.get(
            f"{azents_public_server_url}/chat/v1/sessions/{session_id}/exchange-files",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert list_response.status_code == 200
        items = list_response.json()["items"]
        assert len(items) >= 1
        assert any(item["media_type"] == "text/plain" for item in items)

    def test_upload_then_download_exchange_file(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """file upload t Exchange filet downloadt t t checkt."""
        token, session_id, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        content = b"download test content"
        upload_response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
            session_id,
            filename="download.txt",
            content=content,
            media_type="text/plain",
        )
        assert upload_response.status_code == 200
        uri = upload_response.json()["uri"]
        assert _exchange_uri_is_file_location(uri)
        pytest.skip(
            "Download API still requires exchange_file_id, not opaque Exchange URI."
        )

    def test_upload_then_delete_exchange_file(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """file upload t Exchange filet deletet t t checkt."""
        token, session_id, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        content = b"delete me"
        upload_response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
            session_id,
            filename="deletable.txt",
            content=content,
            media_type="text/plain",
        )
        assert upload_response.status_code == 200
        uri = upload_response.json()["uri"]
        assert _exchange_uri_is_file_location(uri)
        pytest.skip(
            "Delete API still requires exchange_file_id, not opaque Exchange URI."
        )


class TestUploadMessagePath:
    """upload filet chat t t patht verifyt."""

    def test_image_and_file_uploads_reach_model_input(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        mock_openai_url: str,
    ) -> None:
        """t file t user path t uploadt model inputt t."""
        del azents_engine_worker_container
        _reset_mock_openai(mock_openai_url)
        token, session_id, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        image_content = PNG_1X1
        text_content = b"uploaded text file content"

        image_response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
            session_id,
            filename="nul-image.png",
            content=image_content,
            media_type="image/png",
        )
        file_response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
            session_id,
            filename="notes.txt",
            content=text_content,
            media_type="text/plain",
        )
        assert image_response.status_code == 200
        assert file_response.status_code == 200
        image_upload = image_response.json()
        file_upload = file_response.json()
        image_uri = image_upload["uri"]
        file_uri = file_upload["uri"]
        assert "file_part" not in image_upload
        assert "file_part" not in file_upload

        with _connect_existing_chat(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            access_token=token,
            session_id=session_id,
        ) as ws:
            response = requests.post(
                f"{azents_public_server_url}/chat/v1/sessions/{session_id}/inputs",
                headers={**_headers(token), "Content-Type": "application/json"},
                json={
                    "agent_id": agent_id,
                    "client_request_id": f"upload-message-{unique()}",
                    "message": _UPLOAD_PROMPT,
                    "attachments": [image_uri, file_uri],
                },
                timeout=10,
            )
            response.raise_for_status()
            item = _wait_for_user_input(ws, _UPLOAD_PROMPT)

        attachment_items = _object_items(
            item.get("attachments"),
            label="user_input attachments",
        )
        assert len(attachment_items) == 2
        assert attachment_items[0]["uri"] == image_uri
        assert attachment_items[0]["media_type"] == "image/png"
        assert attachment_items[1]["uri"] == file_uri
        assert attachment_items[1]["media_type"] == "text/plain"
        assert "images" not in item
        _assert_file_payload_is_blob_free(item, label="event user_message")
        journal = _wait_for_upload_journal(mock_openai_url)
        assert "\\u0000" not in journal
        _assert_file_payload_is_blob_free(journal, label="model request journal")

        rest_user_message = _wait_for_rest_message(
            azents_public_server_url,
            token,
            session_id,
            _UPLOAD_PROMPT,
        )
        rest_attachment_items = _object_items(
            rest_user_message.get("attachments"),
            label="REST attachments",
        )
        assert {item["uri"] for item in rest_attachment_items} == {
            image_uri,
            file_uri,
        }
        _assert_file_payload_is_blob_free(
            rest_user_message,
            label="REST user message",
        )
        _wait_for_rest_message(
            azents_public_server_url,
            token,
            session_id,
            "Uploaded image and file were observed.",
        )
