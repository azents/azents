"""Safe SDK error fields without provider bodies, headers or exception values."""

from typing import Literal

import litellm
from fastapi import HTTPException
from litellm.proxy._types import ProxyException
from openai import APIError, APIStatusError

ErrorCode = Literal[
    "context_length_exceeded",
    "content_policy_violation",
    "insufficient_quota",
    "rate_limit_exceeded",
    "model_not_found",
    "invalid_api_key",
]


class SafeInferenceError(HTTPException):
    """The regular Proxy serializer consumes these public exception fields."""

    def __init__(
        self,
        *,
        status: int,
        error_type: str,
        param: str | None,
        code: ErrorCode | None,
        message: str,
    ) -> None:
        super().__init__(status_code=status, detail=message)
        self.type = error_type
        self.param = param
        self.code = code


def safe_failure(error: Exception, *, authority_pending: bool) -> SafeInferenceError:
    status = 500
    raw_type: str | None = None
    raw_code: object = None
    if isinstance(error, HTTPException | APIStatusError | litellm.APIError):
        status = error.status_code
    if isinstance(error, APIError | litellm.APIError):
        raw_type, raw_code = error.type, error.code
    if isinstance(error, ProxyException):
        carried = error.code
        if isinstance(carried, int) or (
            isinstance(carried, str) and carried.isdecimal()
        ):
            status = int(carried)
        raw_type = error.type
    if not 400 <= status <= 599:
        status = 500
    error_type = (
        "authentication_error"
        if status == 401
        else "permission_error"
        if status == 403
        else "rate_limit_error"
        if status == 429
        else "invalid_request_error"
        if status < 500
        else "internal_server_error"
    )
    if raw_type in {
        "authentication_error",
        "permission_error",
        "throttling_error",
        "rate_limit_error",
        "invalid_request_error",
        "server_error",
        "internal_server_error",
        "service_unavailable_error",
    }:
        error_type = raw_type
    code: ErrorCode | None = None
    match raw_code:
        case (
            "context_length_exceeded"
            | "content_policy_violation"
            | "insufficient_quota"
            | "rate_limit_exceeded"
            | "model_not_found"
            | "invalid_api_key"
        ):
            code = raw_code
    if isinstance(error, litellm.ContextWindowExceededError):
        code = "context_length_exceeded"
    elif isinstance(error, litellm.ContentPolicyViolationError):
        code = "content_policy_violation"
    if authority_pending:
        param = "azents_authority"
        message = (
            "Agent authentication or authorization failed."
            if status in {401, 403}
            else "Inference authority preparation is unavailable."
        )
    elif isinstance(error, ProxyException):
        param = (
            error.param
            if error.param
            in {
                "request",
                "route",
                "azents_authority",
                "authorization",
            }
            else "request"
        )
        message = (
            "Inference request constraints are not satisfied."
            if status == 400
            else "Inference preparation or admission failed."
        )
    else:
        param = "upstream_provider"
        message = (
            "Upstream provider authentication or permission failed."
            if status in {401, 403}
            else "The admitted model context window was exceeded."
            if code == "context_length_exceeded"
            else "The upstream provider rejected content."
            if code == "content_policy_violation"
            else "Inference request failed."
        )
    return SafeInferenceError(
        status=status, error_type=error_type, param=param, code=code, message=message
    )
