"""Allowlisted classification without exception bodies, headers or diagnostics."""

import json

import httpx2
import pytest
from fastapi import HTTPException
from litellm.proxy._types import ProxyException
from openai import APIStatusError

from azents_llm_proxy.errors import safe_failure


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
@pytest.mark.parametrize("authority_pending", [False, True])
def test_error_status_and_authority_attribution_are_independent(
    status: int, authority_pending: bool
) -> None:
    failure = safe_failure(
        HTTPException(status, detail="private-error-sentinel"),
        authority_pending=authority_pending,
    )
    assert failure.status_code == status
    assert failure.param == (
        "azents_authority" if authority_pending else "upstream_provider"
    )
    assert "sentinel" not in failure.detail


@pytest.mark.parametrize(
    "code",
    ["context_length_exceeded", "content_policy_violation", "insufficient_quota"],
)
def test_safe_provider_categories_survive_without_raw_values(code: str) -> None:
    error = APIStatusError(
        "private-message-sentinel",
        response=httpx2.Response(
            400, request=httpx2.Request("POST", "https://provider.invalid/sentinel")
        ),
        body={
            "type": "invalid_request_error",
            "code": code,
            "param": "private-param-sentinel",
            "message": "private-body-sentinel",
        },
    )
    failure = safe_failure(error, authority_pending=False)
    assert failure.status_code == 400
    assert failure.code == code
    assert failure.type == "invalid_request_error"
    assert failure.param == "upstream_provider"
    assert "sentinel" not in json.dumps(vars(failure))


def test_untrusted_exception_fields_cannot_become_public_classification() -> None:
    failure = safe_failure(
        ProxyException(
            message="private-error-sentinel",
            type="private-type-sentinel",
            param="private-param-sentinel",
            code=403,
        ),
        authority_pending=False,
    )
    assert failure.status_code == 403
    assert failure.type == "permission_error"
    assert failure.param == "request"
    assert failure.code is None
    assert "sentinel" not in json.dumps(vars(failure))
