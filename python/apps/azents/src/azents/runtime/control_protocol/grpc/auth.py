"""Runtime Control gRPC metadata authentication."""

import hmac
from collections.abc import Iterable

import grpc

_AUTHORIZATION_HEADER = "authorization"
_BEARER_PREFIX = "bearer "
_TOKEN_HEADER = "x-azents-runtime-control-token"

GrpcMetadata = grpc.aio.Metadata | Iterable[tuple[str, str | bytes]] | None


class RuntimeControlGrpcAuth:
    """Validate Runtime Control shared-token metadata for gRPC streams."""

    def __init__(self, expected_token: str | None) -> None:
        """Initialize metadata auth with an optional expected token."""
        self._expected_token = _normalized_token(expected_token)

    async def authorize(
        self,
        context: grpc.aio.ServicerContext[object, object],
        *,
        subject: str,
    ) -> None:
        """Abort the RPC when metadata does not contain the expected token."""
        if self._expected_token is None:
            return
        token = _metadata_token(context.invocation_metadata())
        if token is not None and hmac.compare_digest(token, self._expected_token):
            return
        await context.abort(
            grpc.StatusCode.UNAUTHENTICATED,
            f"{subject} Runtime Control token is invalid or missing",
        )
        raise AssertionError("unreachable")


def _normalized_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip()
    return token or None


def _metadata_token(metadata: GrpcMetadata) -> str | None:
    if metadata is None:
        return None
    if isinstance(metadata, grpc.aio.Metadata):
        entries = metadata.items()
    else:
        entries = metadata
    for raw_key, raw_value in entries:
        key = raw_key.lower()
        value = _metadata_value(raw_value)
        if key == _TOKEN_HEADER:
            return _normalized_token(value)
        if key == _AUTHORIZATION_HEADER:
            authorization_token = _bearer_token(value)
            if authorization_token is not None:
                return authorization_token
    return None


def _metadata_value(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return value


def _bearer_token(value: str) -> str | None:
    stripped = value.strip()
    if not stripped.lower().startswith(_BEARER_PREFIX):
        return None
    return _normalized_token(stripped[len(_BEARER_PREFIX) :])
