"""File upload and Exchange file API E2E tests.

Verify uploads and Exchange file listing, download, and deletion.
"""

import base64
import hashlib
import json
import time
from collections.abc import Iterator
from urllib.parse import unquote, urlsplit

import azentsadminclient
import azentspublicclient
import boto3
import pytest
import requests
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.models.chat_upload_prepare_response import (
    ChatUploadPrepareResponse,
)
from pydantic import TypeAdapter, ValidationError
from testcontainers.core.container import DockerContainer
from types_boto3_s3.client import S3Client
from websockets.sync.client import connect as ws_connect
from websockets.sync.connection import Connection

from support.consts import E2E_GENERAL_FILE_MAXIMUM_BYTES
from support.utils import (
    PNG_1X1,
    AgentSessionSetup,
    create_agent_session_setup,
    create_chat_session,
    create_chat_session_with_agent,
    create_second_user_token,
    unique,
    upload_file,
)

_UPLOAD_PROMPT = "Describe uploaded image and file"
_CHAT_UPLOAD_MAX_BYTES = E2E_GENERAL_FILE_MAXIMUM_BYTES
_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


def _exchange_uri_is_file_location(uri: object) -> bool:
    """Return whether a value is an opaque Exchange file-location URI."""
    return (
        isinstance(uri, str)
        and uri.startswith("exchange://")
        and not uri.startswith("exchange://files/")
    )


def _headers(token: str) -> dict[str, str]:
    """Return a Bearer authorization header."""
    return {"Authorization": f"Bearer {token}"}


def _ws_url(http_url: str) -> str:
    """Convert an HTTP URL to its WebSocket equivalent."""
    if http_url.startswith("http://"):
        return "ws://" + http_url.removeprefix("http://")
    if http_url.startswith("https://"):
        return "wss://" + http_url.removeprefix("https://")
    return http_url


def _issue_ticket(
    public_api_client: azentspublicclient.ApiClient,
    access_token: str,
) -> str:
    """Issue a WebSocket connection ticket."""
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
    """Connect to an existing chat session over WebSocket."""
    ticket = _issue_ticket(public_api_client, access_token)
    ws_uri = f"{_ws_url(public_url)}/chat/v1/sessions/{session_id}?ticket={ticket}"
    return ws_connect(ws_uri)


def _recv_event(ws: Connection, *, timeout: float = 10) -> dict[str, object]:
    """Receive one WebSocket event as a JSON object."""
    raw = ws.recv(timeout=timeout)
    return _object_item(json.loads(raw), label="WebSocket payload")


def _object_item(raw_item: object, *, label: str) -> dict[str, object]:
    """Validate and return a JSON object."""
    try:
        return _JSON_OBJECT.validate_python(raw_item)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {raw_item!r}") from exc


def _object_items(raw_items: object, *, label: str) -> list[dict[str, object]]:
    """Validate and return a list of JSON objects."""
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
    """Wait for a durable user-message event with the expected content."""
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
    """Return text from either string or structured event content."""
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
    """Assert that a file payload contains no raw provider blob data."""
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
    """Return the AIMock request journal payload."""
    return requests.get(f"{mock_openai_url}/v1/_requests", timeout=10).json()


def _scenario_model_requests(payload: object, *, prompt: str) -> list[str]:
    """Select only provider request bodies belonging to this unique scenario."""
    bodies: list[str] = []
    for entry in _object_items(payload, label="model request journal"):
        body = json.dumps(
            _object_item(entry.get("body"), label="model request body"),
            ensure_ascii=False,
        )
        if prompt in body:
            bodies.append(body)
    return bodies


def _reset_mock_openai(mock_openai_url: str) -> None:
    """Reset the AIMock request journal."""
    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()


def _wait_for_upload_journal(
    mock_openai_url: str,
    timeout: float = 90,
) -> str:
    """Wait until the AIMock journal contains the uploaded model input."""
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
    """Fetch one REST history event page."""
    response = requests.get(
        f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return _object_item(response.json(), label="list history response")


def _message_items(payload: dict[str, object]) -> list[dict[str, object]]:
    """Return user and assistant message items from REST history."""
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
    """Return the REST history message with the expected content."""
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
    """Wait for REST history to contain the expected message."""
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


class TestFileUpload:
    """Test the file upload API."""

    def test_upload_file(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """A successful file upload returns URI, media type, and size."""
        token, _, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        content = PNG_1X1
        response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
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
        """Unauthenticated Agent upload returns 401."""
        response = requests.post(
            f"{azents_public_server_url}/chat/v1/agents/"
            "00000000000000000000000000000000/uploads",
            json={
                "filename": "test.txt",
                "media_type": "text/plain",
                "size": 5,
                "sha256": hashlib.sha256(b"hello").hexdigest(),
            },
            timeout=10,
        )
        assert response.status_code == 401

    def test_upload_to_nonexistent_agent_returns_404(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """Uploading to a nonexistent Agent returns 404."""
        token, _, _ = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        response = upload_file(
            azents_public_server_url,
            token,
            "00000000000000000000000000000000",
            filename="test.txt",
            content=b"hello",
            media_type="text/plain",
        )
        assert response.status_code == 404

    def test_upload_to_other_users_agent_returns_403(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """Uploading to another user's Agent returns 403."""
        _, _, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        other_token = create_second_user_token(public_api_client, admin_api_client)

        response = upload_file(
            azents_public_server_url,
            other_token,
            agent_id,
            filename="test.txt",
            content=b"hello",
            media_type="text/plain",
        )
        assert response.status_code == 403

    @pytest.mark.parametrize(
        ("size", "expected_status"),
        [
            (_CHAT_UPLOAD_MAX_BYTES + 1, 400),
            (128 * 1024 * 1024 + 1, 422),
        ],
        ids=["configured-limit-exceeded", "schema-ceiling-exceeded"],
    )
    def test_upload_exceeding_size_limit_rejects_metadata(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        size: int,
        expected_status: int,
    ) -> None:
        """Configured and schema bounds reject metadata before any object PUT."""
        token, _, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        response = requests.post(
            f"{azents_public_server_url}/chat/v1/agents/{agent_id}/uploads",
            headers=_headers(token),
            json={
                "filename": "large.bin",
                "media_type": "application/octet-stream",
                "size": size,
                "sha256": hashlib.sha256(b"oversized metadata only").hexdigest(),
            },
            timeout=10,
        )
        assert response.status_code == expected_status
        assert "put_url" not in response.json()


# ---------------------------------------------------------------------------
# Exchange Files
# ---------------------------------------------------------------------------


@pytest.fixture
def chat_upload_setup(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> AgentSessionSetup:
    """Create upload authority through the ordinary user-facing APIs."""
    return create_agent_session_setup(
        public_api_client, admin_api_client, azents_public_server_url
    )


@pytest.fixture
def chat_upload_s3(
    rustfs_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
) -> Iterator[S3Client]:
    """Observe native S3 integrity without writing product or fixture state."""
    host = rustfs_container.get_container_host_ip()
    port = rustfs_container.get_exposed_port(9000)
    client: S3Client = boto3.client(
        "s3",
        endpoint_url=f"http://{host}:{port}",
        aws_access_key_id=rustfs_access_key,
        aws_secret_access_key=rustfs_secret_key,
    )
    try:
        yield client
    finally:
        client.close()


def _prepare_chat_upload(
    server_url: str,
    setup: AgentSessionSetup,
    content: bytes,
) -> ChatUploadPrepareResponse:
    """Authorize metadata only; preparation never exposes an attachment."""
    response = requests.post(
        f"{server_url}/chat/v1/agents/{setup.agent_id}/uploads",
        headers=_headers(setup.access_token),
        json={
            "filename": "direct-upload.bin",
            "media_type": "application/octet-stream",
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        timeout=10,
    )
    assert response.status_code == 200
    payload = _object_item(response.json(), label="Chat upload preparation")
    assert set(payload) == {"upload_id", "put_url", "put_headers", "expires_at"}
    return ChatUploadPrepareResponse.model_validate(payload)


def _finalize_chat_upload(
    server_url: str,
    setup: AgentSessionSetup,
    upload_id: str,
) -> requests.Response:
    """Finalize using current user authority without sending file bytes."""
    return requests.post(
        f"{server_url}/chat/v1/agents/{setup.agent_id}/uploads/{upload_id}/finalize",
        headers=_headers(setup.access_token),
        timeout=180,
    )


def _chat_ingress_key(ticket: ChatUploadPrepareResponse, bucket: str) -> str:
    """Read the exact signed fixture object identity for read-only S3 evidence."""
    prefix = f"/{bucket}/"
    path = unquote(urlsplit(ticket.put_url).path)
    assert path.startswith(prefix)
    key = path.removeprefix(prefix)
    assert key.startswith("exchange-uploads/")
    assert key.endswith(f"/{ticket.upload_id}/ingress")
    return key


def _assert_no_chat_publication(
    s3: S3Client, bucket: str, ticket: ChatUploadPrepareResponse
) -> None:
    """An unfinalized operation creates no source or Exchange publication."""
    ingress_key = _chat_ingress_key(ticket, bucket)
    workspace_id = ingress_key.split("/")[1]
    publications = s3.list_objects_v2(
        Bucket=bucket, Prefix=f"exchange/{workspace_id}/files/"
    )
    assert not publications.get("Contents")
    objects = s3.list_objects_v2(
        Bucket=bucket, Prefix=ingress_key.removesuffix("ingress")
    )
    assert all(entry["Key"] == ingress_key for entry in objects.get("Contents", []))


class TestDirectChatUpload:
    """Exercise real RustFS checksum and immutable Exchange publication."""

    @pytest.mark.parametrize(
        "size",
        [_CHAT_UPLOAD_MAX_BYTES - 1, _CHAT_UPLOAD_MAX_BYTES],
        ids=["below-configured-limit", "at-configured-limit"],
    )
    def test_configured_boundary_native_checksum_and_idempotent_publication(
        self,
        azents_public_server_url: str,
        chat_upload_setup: AgentSessionSetup,
        chat_upload_s3: S3Client,
        s3_bucket_name: str,
        mock_openai_url: str,
        size: int,
    ) -> None:
        """Small injected limits exercise real checksum/copy/publication bounds."""
        content = b"x" * size
        digest = hashlib.sha256(content).hexdigest()
        checksum = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
        ticket = _prepare_chat_upload(
            azents_public_server_url, chat_upload_setup, content
        )
        assert ticket.put_headers["x-amz-checksum-sha256"] == checksum
        assert "content-length" not in ticket.put_headers
        assert "uploadId=" not in ticket.put_url
        _assert_no_chat_publication(chat_upload_s3, s3_bucket_name, ticket)
        missing_body = _finalize_chat_upload(
            azents_public_server_url, chat_upload_setup, ticket.upload_id
        )
        assert missing_body.status_code == 400
        _assert_no_chat_publication(chat_upload_s3, s3_bucket_name, ticket)

        uploaded = requests.put(
            ticket.put_url,
            headers=ticket.put_headers,
            data=content,
            timeout=180,
            verify=False,
            allow_redirects=False,
        )
        assert uploaded.status_code == 200
        ingress_key = _chat_ingress_key(ticket, s3_bucket_name)
        ingress = chat_upload_s3.head_object(
            Bucket=s3_bucket_name, Key=ingress_key, ChecksumMode="ENABLED"
        )
        assert ingress["ContentLength"] == size
        assert ingress["ChecksumSHA256"] == checksum
        _assert_no_chat_publication(chat_upload_s3, s3_bucket_name, ticket)

        finalized = _finalize_chat_upload(
            azents_public_server_url, chat_upload_setup, ticket.upload_id
        )
        assert finalized.status_code == 200
        published = _object_item(finalized.json(), label="Chat upload publication")
        assert published["size"] == size
        assert _exchange_uri_is_file_location(published["uri"])
        assert published["media_type"] == "application/octet-stream"
        assert not {"put_url", "put_headers", "expires_at", "file_part"} & set(
            published
        )
        repeated = _finalize_chat_upload(
            azents_public_server_url, chat_upload_setup, ticket.upload_id
        )
        assert repeated.status_code == 200
        assert repeated.json() == published

        workspace_id = ingress_key.split("/")[1]
        source_key = ingress_key.removesuffix("ingress") + "source"
        source = chat_upload_s3.head_object(
            Bucket=s3_bucket_name, Key=source_key, ChecksumMode="ENABLED"
        )
        assert source["ContentLength"] == size
        assert source["Metadata"]["azents-transfer-sha256"] == digest
        original_key = (
            f"exchange/{workspace_id}/files/{published['attachment_id']}/original"
        )
        original = chat_upload_s3.get_object(
            Bucket=s3_bucket_name, Key=original_key, ChecksumMode="ENABLED"
        )
        assert original["ContentLength"] == size
        assert original["Metadata"]["azents-product-publication-sha256"] == digest
        assert (
            original["Metadata"]["azents-product-publication-id"]
            == published["attachment_id"]
        )
        observed_digest = hashlib.sha256()
        observed_size = 0
        body = original["Body"]
        try:
            for chunk in body.iter_chunks(chunk_size=1024 * 1024):
                observed_digest.update(chunk)
                observed_size += len(chunk)
        finally:
            body.close()
        assert observed_size == size
        assert observed_digest.hexdigest() == digest
        publications = chat_upload_s3.list_objects_v2(
            Bucket=s3_bucket_name, Prefix=f"exchange/{workspace_id}/files/"
        )
        assert [entry["Key"] for entry in publications.get("Contents", [])] == [
            original_key
        ]
        multipart = chat_upload_s3.list_multipart_uploads(
            Bucket=s3_bucket_name, Prefix=ingress_key.removesuffix("ingress")
        )
        assert not multipart.get("Uploads")
        prompt = f"Inspect the large direct attachment {ticket.upload_id}."
        submitted = requests.post(
            f"{azents_public_server_url}/chat/v1/sessions/"
            f"{chat_upload_setup.session_id}/inputs",
            headers=_headers(chat_upload_setup.access_token),
            json={
                "agent_id": chat_upload_setup.agent_id,
                "client_request_id": f"large-upload-{unique()}",
                "message": prompt,
                "inference_profile": {
                    "model_target_label": "default",
                    "reasoning_effort": None,
                    "enabled_execution_options": [],
                },
                "attachments": [published["uri"]],
            },
            timeout=10,
        )
        submitted.raise_for_status()
        message = _wait_for_rest_message(
            azents_public_server_url,
            chat_upload_setup.access_token,
            chat_upload_setup.session_id,
            prompt,
        )
        attachments = _object_items(
            message["attachments"], label="large user-message attachments"
        )
        assert len(attachments) == 1
        assert attachments[0]["uri"] == published["uri"]
        assert attachments[0]["size"] == size
        deadline = time.monotonic() + 90
        warning = (
            f"{size} bytes > 1000000 bytes. This file was not stored as model input."
        )
        while time.monotonic() < deadline:
            scenario_requests = _scenario_model_requests(
                _mock_openai_journal_payload(mock_openai_url), prompt=prompt
            )
            if any(warning in request for request in scenario_requests):
                break
            time.sleep(0.5)
        else:
            raise AssertionError(
                "Large attachment model-input warning was not observed."
            )
        _assert_file_payload_is_blob_free(message, label="large user message")
        for request in scenario_requests:
            assert len(request) < 1024 * 1024
            _assert_file_payload_is_blob_free(request, label="large model input")

    @pytest.mark.parametrize(
        "failure", ["missing_checksum", "wrong_checksum", "wrong_body"]
    )
    def test_invalid_put_never_publishes_and_same_operation_can_retry(
        self,
        failure: str,
        azents_public_server_url: str,
        chat_upload_setup: AgentSessionSetup,
        chat_upload_s3: S3Client,
        s3_bucket_name: str,
    ) -> None:
        """Signature/native digest rejection leaves no attachment or source."""
        content = b"checksum-bound direct upload"
        ticket = _prepare_chat_upload(
            azents_public_server_url, chat_upload_setup, content
        )
        headers = dict(ticket.put_headers)
        uploaded_content = content
        if failure == "missing_checksum":
            del headers["x-amz-checksum-sha256"]
        elif failure == "wrong_checksum":
            headers["x-amz-checksum-sha256"] = base64.b64encode(b"\x00" * 32).decode()
        else:
            uploaded_content = b"z" * len(content)
        rejected = requests.put(
            ticket.put_url,
            headers=headers,
            data=uploaded_content,
            timeout=30,
            verify=False,
            allow_redirects=False,
        )
        assert rejected.status_code in {400, 403}
        failed = _finalize_chat_upload(
            azents_public_server_url, chat_upload_setup, ticket.upload_id
        )
        assert failed.status_code == 400
        _assert_no_chat_publication(chat_upload_s3, s3_bucket_name, ticket)
        retried = requests.put(
            ticket.put_url,
            headers=ticket.put_headers,
            data=content,
            timeout=30,
            verify=False,
            allow_redirects=False,
        )
        assert retried.status_code == 200
        finalized = _finalize_chat_upload(
            azents_public_server_url, chat_upload_setup, ticket.upload_id
        )
        assert finalized.status_code == 200
        assert finalized.json()["size"] == len(content)

    def test_finalize_rechecks_current_owner_before_and_after_publication(
        self,
        azents_public_server_url: str,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        chat_upload_setup: AgentSessionSetup,
        chat_upload_s3: S3Client,
        s3_bucket_name: str,
    ) -> None:
        """A PUT capability never gives another API caller publication authority."""
        content = b"owner-scoped direct upload"
        ticket = _prepare_chat_upload(
            azents_public_server_url, chat_upload_setup, content
        )
        uploaded = requests.put(
            ticket.put_url,
            headers=ticket.put_headers,
            data=content,
            timeout=30,
            verify=False,
            allow_redirects=False,
        )
        assert uploaded.status_code == 200
        other_token = create_second_user_token(public_api_client, admin_api_client)
        finalize_url = (
            f"{azents_public_server_url}/chat/v1/agents/{chat_upload_setup.agent_id}"
            f"/uploads/{ticket.upload_id}/finalize"
        )
        denied = requests.post(finalize_url, headers=_headers(other_token), timeout=10)
        assert denied.status_code == 403
        _assert_no_chat_publication(chat_upload_s3, s3_bucket_name, ticket)
        anonymous = requests.post(finalize_url, timeout=10)
        assert anonymous.status_code == 401
        published = _finalize_chat_upload(
            azents_public_server_url, chat_upload_setup, ticket.upload_id
        )
        assert published.status_code == 200
        denied_replay = requests.post(
            finalize_url, headers=_headers(other_token), timeout=10
        )
        assert denied_replay.status_code == 403
        replay = _finalize_chat_upload(
            azents_public_server_url, chat_upload_setup, ticket.upload_id
        )
        assert replay.status_code == 200
        assert replay.json() == published.json()

    def test_chat_upload_api_rejects_multipart_and_missing_manifest(
        self,
        azents_public_server_url: str,
        chat_upload_setup: AgentSessionSetup,
    ) -> None:
        """There is no legacy body relay or checksum-free preparation fallback."""
        base = f"{azents_public_server_url}/chat/v1/agents/{chat_upload_setup.agent_id}"
        headers = _headers(chat_upload_setup.access_token)
        legacy = requests.post(
            f"{base}/upload",
            files={"file": ("legacy.txt", b"body", "text/plain")},
            headers=headers,
            timeout=10,
        )
        assert legacy.status_code == 404
        multipart = requests.post(
            f"{base}/uploads",
            files={"file": ("legacy.txt", b"body", "text/plain")},
            headers=headers,
            timeout=10,
        )
        assert multipart.status_code == 422
        missing_digest = requests.post(
            f"{base}/uploads",
            json={"filename": "test.txt", "media_type": "text/plain", "size": 4},
            headers=headers,
            timeout=10,
        )
        assert missing_digest.status_code == 422


@pytest.mark.skip(reason="Session-scoped Exchange file listing API is not available.")
class TestExchangeFiles:
    """Test the Exchange file API."""

    def test_list_exchange_files_empty(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """A session without files returns an empty list."""
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
        """Listing Exchange files without authentication returns 401."""
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
        """Listing another user's Exchange files returns 403."""
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
        """A file upload appears in the Exchange file list."""
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
        """An uploaded Exchange file can be downloaded."""
        token, _, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        content = b"download test content"
        upload_response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
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
        """An uploaded Exchange file can be deleted."""
        token, _, agent_id = create_chat_session_with_agent(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )

        content = b"delete me"
        upload_response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
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
    """Verify uploaded files through the chat message path."""

    def test_image_and_file_uploads_reach_model_input(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        mock_openai_url: str,
    ) -> None:
        """Image and file uploads reach model input through the user path."""
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
            filename="nul-image.png",
            content=image_content,
            media_type="image/png",
        )
        file_response = upload_file(
            azents_public_server_url,
            token,
            agent_id,
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
                    "inference_profile": {
                        "model_target_label": "default",
                        "reasoning_effort": None,
                        "enabled_execution_options": [],
                    },
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
