"""Runtime Control gRPC metadata authentication."""

from collections.abc import Iterable
from typing import Protocol

import grpc

from azents.core.enums import RuntimeProviderAuthMethod
from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredential,
    RuntimeRunnerCredentialInvalid,
)
from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialAuthentication,
    RuntimeProviderCredentialUnavailable,
)

_AUTHORIZATION_HEADER = "authorization"
_AUTH_METHOD_HEADER = "x-azents-runtime-provider-auth-method"
_BEARER_PREFIX = "bearer "

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

    async def authenticate_provider(
        self,
        *,
        method: RuntimeProviderAuthMethod,
        secret: str,
    ) -> RuntimeProviderCredentialAuthentication:
        """Resolve one explicitly selected Provider auth method."""
        ...


class RuntimeRunnerCredentialAuthenticator(Protocol):
    """Authenticate and authorize Runtime-bound Runner credentials."""

    async def authenticate_runner(
        self,
        secret: str,
    ) -> RuntimeRunnerCredential:
        """Return verified current Runtime claims."""
        ...

    async def authorize_runner(
        self,
        credential: RuntimeRunnerCredential,
    ) -> bool:
        """Return whether verified claims still match durable Runtime state."""
        ...


class RuntimeRunnerCredentialGrpcAuth:
    """Authenticate a Runner stream with Runtime-bound signed evidence."""

    def __init__(
        self,
        authenticator: RuntimeRunnerCredentialAuthenticator,
    ) -> None:
        """Initialize Runner credential authentication."""
        self._authenticator = authenticator

    async def authenticate(
        self,
        context: grpc.aio.ServicerContext[object, object],
    ) -> RuntimeRunnerCredential:
        """Resolve one Runner credential to current durable Runtime claims."""
        secret = _single_bearer_credential(context.invocation_metadata())
        if secret is None:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Runner credential is missing",
            )
            raise AssertionError("unreachable")
        try:
            return await self._authenticator.authenticate_runner(secret)
        except RuntimeRunnerCredentialInvalid:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Runner credential is invalid or unavailable",
            )
            raise AssertionError("unreachable") from None


class RuntimeProviderCredentialGrpcAuth:
    """Authenticate a Provider stream with its Provider-bound credential."""

    def __init__(self, authenticator: RuntimeProviderCredentialAuthenticator) -> None:
        """Initialize Provider credential authentication."""
        self._authenticator = authenticator

    async def authenticate(
        self,
        context: grpc.aio.ServicerContext[object, object],
    ) -> RuntimeProviderCredentialAuthentication:
        """Resolve one explicitly selected Provider authentication method."""
        method = _provider_auth_method(context.invocation_metadata())
        secret = _single_bearer_credential(context.invocation_metadata())
        if method is None or secret is None:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Provider authentication method or credential is missing",
            )
            raise AssertionError("unreachable")
        try:
            return await self._authenticator.authenticate_provider(
                method=method,
                secret=secret,
            )
        except RuntimeProviderCredentialUnavailable:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Provider authentication is invalid or unavailable",
            )
            raise AssertionError("unreachable") from None


def _normalized_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip()
    return token or None


def _single_bearer_credential(metadata: GrpcMetadata) -> str | None:
    """Read exactly one credential from standard bearer metadata."""
    if metadata is None:
        return None
    entries = metadata
    values = [
        _bearer_token(_metadata_value(raw_value))
        for raw_key, raw_value in entries
        if raw_key.lower() == _AUTHORIZATION_HEADER
    ]
    if len(values) != 1:
        return None
    return values[0]


def _provider_auth_method(metadata: GrpcMetadata) -> RuntimeProviderAuthMethod | None:
    """Read the required explicit Provider authentication method."""
    if metadata is None:
        return None
    entries = metadata
    values = [
        _normalized_token(_metadata_value(raw_value))
        for raw_key, raw_value in entries
        if raw_key.lower() == _AUTH_METHOD_HEADER
    ]
    if len(values) != 1 or values[0] is None:
        return None
    try:
        return RuntimeProviderAuthMethod(values[0])
    except ValueError:
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
