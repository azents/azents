"""Runtime Control gRPC metadata authentication."""

import hmac
from collections.abc import Iterable
from typing import Protocol

import grpc

from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialAuthentication,
    RuntimeProviderCredentialUnavailable,
)

_AUTHORIZATION_HEADER = "authorization"
_BEARER_PREFIX = "bearer "
_TOKEN_HEADER = "x-azents-runtime-control-token"

GrpcMetadata = grpc.aio.Metadata | Iterable[tuple[str, str | bytes]] | None


class RuntimeProviderCredentialAuthenticator(Protocol):
    """Authenticate Provider credentials independently of Runner transport auth."""

    async def authenticate_credential(
        self,
        *,
        secret: str,
    ) -> RuntimeProviderCredentialAuthentication:
        """Resolve a Provider credential to its durable identity."""
        ...


class RuntimeControlGrpcAuth:
    """Validate shared transport-token metadata for Runtime Runner streams."""

    def __init__(self, expected_token: str | None) -> None:
        """Initialize metadata auth with an optional expected token."""
        self._expected_token = _normalized_token(expected_token)

    async def authorize(
        self,
        context: grpc.aio.ServicerContext[object, object],
        *,
        subject: str,
    ) -> None:
        """Abort the Runner RPC when metadata does not contain the expected token."""
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


class RuntimeProviderCredentialGrpcAuth:
    """Authenticate a Provider stream with its Provider-bound credential."""

    def __init__(self, authenticator: RuntimeProviderCredentialAuthenticator) -> None:
        """Initialize Provider credential authentication."""
        self._authenticator = authenticator

    async def authenticate(
        self,
        context: grpc.aio.ServicerContext[object, object],
    ) -> RuntimeProviderCredentialAuthentication:
        """Resolve metadata bearer credentials or abort the Provider stream."""
        secret = _provider_metadata_credential(context.invocation_metadata())
        if secret is None:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Provider credential is missing",
            )
            raise AssertionError("unreachable")
        try:
            return await self._authenticator.authenticate_credential(secret=secret)
        except RuntimeProviderCredentialUnavailable:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Provider credential is invalid or unavailable",
            )
            raise AssertionError("unreachable") from None


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


def _provider_metadata_credential(metadata: GrpcMetadata) -> str | None:
    """Read a Provider credential from standard bearer metadata only."""
    if metadata is None:
        return None
    entries = metadata.items() if isinstance(metadata, grpc.aio.Metadata) else metadata
    for raw_key, raw_value in entries:
        if raw_key.lower() == _AUTHORIZATION_HEADER:
            return _bearer_token(_metadata_value(raw_value))
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
