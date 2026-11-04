"""Custom auth route closure and request-private credential attribution."""

import json
from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from azents_llm_contract.authority import ModelListResponse
from fastapi import Request
from litellm.proxy._types import ProxyException
from litellm.proxy.auth.user_api_key_auth import _custom_auth_token_for_this_request

from azents_llm_proxy.auth import AgentAuthentication, BoundAuth
from azents_llm_proxy.authority import (
    AuthorityClient,
    AuthorityDenied,
    AuthorityUnavailable,
)
from azents_llm_proxy.authority_test import AGENT, IDENTITY, binding
from azents_llm_proxy.context import RequestContext
from azents_llm_proxy.request_test import request as body


def incoming(
    *, method: str, path: str, headers: list[tuple[bytes, bytes]], payload: object
) -> Request:
    async def receive() -> dict[str, object]:
        return {
            "type": "http.request",
            "body": json.dumps(payload).encode(),
            "more_body": False,
        }

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": headers,
        },
        receive,
    )


@pytest.fixture
def context() -> Iterator[RequestContext]:
    value = RequestContext(clients=None)
    with value.scope():
        yield value


async def test_binding_is_private_and_raw_bearer_never_enters_auth_fields(
    context: RequestContext,
) -> None:
    authority = AsyncMock(spec=AuthorityClient)
    authority.resolve.return_value = binding()
    auth = await AgentAuthentication(authority, context).authenticate(
        incoming(
            method="POST",
            path="/v1/responses",
            headers=[(b"authorization", f"Bearer {AGENT}".encode())],
            payload=body(),
        ),
        api_key="ignored-extractor-value",
    )
    assert auth.inference().identity == IDENTITY
    assert auth.selectors().model == "model"
    assert auth.user_id == "agent" and auth.team_id == "workspace"
    serialized = auth.model_dump_json()
    assert AGENT not in serialized and "provider-sentinel" not in serialized
    assert "private-prompt" not in serialized
    assert "provider-sentinel" not in repr(auth)
    assert auth.api_key == "token"


async def test_request_cleanup_revokes_original_and_upstream_auth_copies() -> None:
    context = RequestContext(clients=None)
    authority = AsyncMock(spec=AuthorityClient)
    authority.resolve.return_value = binding()
    with context.scope():
        auth = await AgentAuthentication(authority, context).authenticate(
            incoming(
                method="POST",
                path="/v1/responses",
                headers=[(b"authorization", f"Bearer {AGENT}".encode())],
                payload=body(),
            ),
            api_key=AGENT,
        )
        copied = _custom_auth_token_for_this_request(auth)
        assert isinstance(copied, BoundAuth)
        assert copied is not auth
        assert copied.inference() is auth.inference()
        assert copied.selectors() is auth.selectors()
        serialized = copied.model_dump_json()
        assert AGENT not in serialized and "provider-sentinel" not in serialized
        assert "private-prompt" not in serialized
        assert "provider-sentinel" not in repr(copied)
    for ended in (auth, copied):
        with pytest.raises(
            ProxyException, match="Approved inference context is missing"
        ):
            ended.inference()
        with pytest.raises(ProxyException, match="Approved request context is missing"):
            ended.selectors()


async def test_nested_scope_cleanup_does_not_revoke_other_request_copy() -> None:
    context = RequestContext(clients=None)
    authority = AsyncMock(spec=AuthorityClient)
    authority.resolve.return_value = binding()
    authentication = AgentAuthentication(authority, context)

    async def authenticate() -> BoundAuth:
        return await authentication.authenticate(
            incoming(
                method="POST",
                path="/v1/responses",
                headers=[(b"authorization", f"Bearer {AGENT}".encode())],
                payload=body(),
            ),
            api_key=AGENT,
        )

    with context.scope():
        first = await authenticate()
        first_copy = _custom_auth_token_for_this_request(first)
        assert isinstance(first_copy, BoundAuth)
        with context.scope():
            second = await authenticate()
            second_copy = _custom_auth_token_for_this_request(second)
            assert isinstance(second_copy, BoundAuth)
            assert second_copy.inference() is second.inference()
        for ended in (second, second_copy):
            with pytest.raises(ProxyException):
                ended.inference()
            with pytest.raises(ProxyException):
                ended.selectors()
        assert first_copy.inference() is first.inference()
        assert first_copy.selectors() is first.selectors()
    for ended in (first, first_copy):
        with pytest.raises(ProxyException):
            ended.inference()
        with pytest.raises(ProxyException):
            ended.selectors()


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/responses"),
        ("GET", "/models"),
        ("POST", "/v1/chat/completions"),
        ("POST", "/key/generate"),
        ("GET", "/v1/responses/resp_foreign"),
        ("POST", "/v1/images/generations"),
        ("GET", "/model/info"),
        ("POST", "/v1/responses/"),
    ],
)
async def test_unlisted_operations_fail_before_authority(
    method: str, path: str, context: RequestContext
) -> None:
    authority = AsyncMock(spec=AuthorityClient)
    with pytest.raises(ProxyException):
        await AgentAuthentication(authority, context).authenticate(
            incoming(
                method=method,
                path=path,
                headers=[(b"authorization", f"Bearer {AGENT}".encode())],
                payload=body(),
            ),
            api_key=AGENT,
        )
    authority.resolve.assert_not_called()
    authority.list_models.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"x-api-key", AGENT.encode())],
        [(b"authorization", f"Bearer {AGENT}".encode()), (b"api-key", b"override")],
        [
            (b"authorization", f"Bearer {AGENT}".encode()),
            (b"authorization", b"Bearer other"),
        ],
        [(b"authorization", b"Basic wrong")],
        [(b"authorization", b"Bearer two tokens")],
    ],
)
async def test_alias_duplicate_and_malformed_authorization_is_not_accepted(
    headers: list[tuple[bytes, bytes]],
    context: RequestContext,
) -> None:
    authority = AsyncMock(spec=AuthorityClient)
    with pytest.raises(ProxyException):
        await AgentAuthentication(authority, context).authenticate(
            incoming(
                method="POST", path="/v1/responses", headers=headers, payload=body()
            ),
            api_key=AGENT,
        )
    authority.resolve.assert_not_called()


async def test_models_has_no_inference_secret_binding(context: RequestContext) -> None:
    authority = AsyncMock(spec=AuthorityClient)
    authority.list_models.return_value = ModelListResponse(
        identity=IDENTITY, models=("one", "two")
    )
    auth = await AgentAuthentication(authority, context).authenticate(
        incoming(
            method="GET",
            path="/v1/models",
            headers=[(b"authorization", f"Bearer {AGENT}".encode())],
            payload=None,
        ),
        api_key=AGENT,
    )
    assert auth.models == ["one", "two"]
    with pytest.raises(ProxyException):
        auth.inference()
    authority.resolve.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        AuthorityDenied(401),
        AuthorityDenied(403),
        AuthorityUnavailable("private diagnostic"),
    ],
)
async def test_authority_failure_does_not_turn_into_raw_secret_diagnostic(
    error: Exception,
    context: RequestContext,
) -> None:
    authority = AsyncMock(spec=AuthorityClient)
    authority.resolve.side_effect = error
    with pytest.raises(ProxyException) as caught:
        await AgentAuthentication(authority, context).authenticate(
            incoming(
                method="POST",
                path="/v1/responses",
                headers=[(b"authorization", f"Bearer {AGENT}".encode())],
                payload=body(),
            ),
            api_key=AGENT,
        )
    assert AGENT not in str(caught.value)
    assert "private diagnostic" not in str(caught.value)
