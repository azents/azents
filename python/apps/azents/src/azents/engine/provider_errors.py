"""Map supported SDK failure evidence into the existing safe error contract."""

import dataclasses
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING

import anthropic
import httpx
import httpx2
import openai
from botocore.exceptions import (
    ClientError,
    ReadTimeoutError,
)
from botocore.exceptions import (
    ConnectionError as AWSConnectionError,
)
from google.genai.errors import APIError as GoogleAPIError
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

from azents.core.type_guards import is_string_object_dict
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    extract_provider_message_text,
    model_provider_failure,
)

if TYPE_CHECKING:
    from azents.engine.model_stream import ModelStreamCallContext


SDK_PROVIDER_ERRORS = (
    openai.APIError,
    anthropic.APIError,
    GoogleAPIError,
    ClientError,
    AWSConnectionError,
    ReadTimeoutError,
    httpx.TransportError,
    httpx2.TransportError,
    ModelAPIError,
)


@dataclasses.dataclass(frozen=True)
class _SDKErrorEvidence:
    """Scalar provider evidence extracted before safe classification."""

    body: object
    status: int | None
    message: str | None
    code: object
    error_type: object
    parameter: object
    headers: Mapping[str, str] | None


def map_model_provider_error(
    error: Exception,
    *,
    call_context: ModelStreamCallContext,
) -> ModelProviderFailure:
    """Classify supported SDK errors; unrelated failures retain their identity."""
    exc = error
    if isinstance(exc, ModelProviderFailure):
        return exc
    if not isinstance(exc, SDK_PROVIDER_ERRORS):
        raise exc
    if isinstance(exc, ModelAPIError) and isinstance(
        exc.__cause__, SDK_PROVIDER_ERRORS
    ):
        return map_model_provider_error(exc.__cause__, call_context=call_context)
    evidence = _sdk_error_evidence(exc)
    body = _error_body(evidence.body)
    return model_provider_failure(
        operation=call_context.call_kind,
        provider=call_context.provider,
        model=call_context.model,
        integration=call_context.provider_integration_id,
        provider_message=(
            extract_provider_message_text(body.get("message"))
            or extract_provider_message_text(body.get("Message"))
            or extract_provider_message_text(evidence.message)
        ),
        status_code=evidence.status,
        provider_code=body.get("code") or body.get("Code") or evidence.code,
        provider_error_type=body.get("type") or evidence.error_type,
        provider_error_param=body.get("param") or evidence.parameter,
        retry_hint_seconds=_retry_after(evidence.headers),
        category=(
            ModelProviderFailureCategory.TRANSPORT
            if isinstance(
                exc,
                AWSConnectionError
                | ReadTimeoutError
                | httpx.TransportError
                | httpx2.TransportError,
            )
            else None
        ),
    )


def _sdk_error_evidence(exc: Exception) -> _SDKErrorEvidence:
    """Read only supported public exception fields, never serialized raw errors."""
    match exc:
        case openai.APIError():
            return _SDKErrorEvidence(
                body=exc.body,
                status=exc.status_code
                if isinstance(exc, openai.APIStatusError)
                else None,
                message=exc.message,
                code=exc.code,
                error_type=exc.type or type(exc).__name__,
                parameter=exc.param,
                headers=exc.response.headers
                if isinstance(exc, openai.APIStatusError)
                else None,
            )
        case anthropic.APIError():
            return _SDKErrorEvidence(
                body=exc.body,
                status=exc.status_code
                if isinstance(exc, anthropic.APIStatusError)
                else None,
                message=exc.message,
                code=None,
                error_type=type(exc).__name__,
                parameter=None,
                headers=exc.response.headers
                if isinstance(exc, anthropic.APIStatusError)
                else None,
            )
        case GoogleAPIError():
            return _SDKErrorEvidence(
                body=exc.details,
                status=exc.code,
                message=exc.message,
                code=exc.status,
                error_type=type(exc).__name__,
                parameter=None,
                headers=None,
            )
        case ClientError():
            metadata = _error_body(exc.response.get("ResponseMetadata"))
            status = metadata.get("HTTPStatusCode")
            return _SDKErrorEvidence(
                body=exc.response,
                status=status if isinstance(status, int) else None,
                message=None,
                code=None,
                error_type=type(exc).__name__,
                parameter=None,
                headers=None,
            )
        case ModelHTTPError():
            return _SDKErrorEvidence(
                body=exc.body,
                status=exc.status_code,
                message=None,
                code=None,
                error_type=type(exc).__name__,
                parameter=None,
                headers=exc.headers,
            )
        case (
            AWSConnectionError()
            | ReadTimeoutError()
            | httpx.TransportError()
            | httpx2.TransportError()
        ):
            return _SDKErrorEvidence(
                body=None,
                status=None,
                message=None,
                code=None,
                error_type=type(exc).__name__,
                parameter=None,
                headers=None,
            )
        case ModelAPIError():
            return _SDKErrorEvidence(
                body=None,
                status=None,
                message=None,
                code=None,
                error_type=type(exc).__name__,
                parameter=None,
                headers=None,
            )
        case _:
            raise exc


def _error_body(value: object) -> dict[str, object]:
    """Select a typed error payload from the public SDK body."""
    if not is_string_object_dict(value):
        return {}
    nested = value.get("error") or value.get("Error")
    return nested if is_string_object_dict(nested) else value


def _retry_after(headers: Mapping[str, str] | None) -> float | None:
    """Retain only a bounded finite numeric Retry-After hint."""
    if headers is None:
        return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and 0 <= seconds <= 86_400 else None
