"""Deployment-rooted credentials for trusted Runtime transfer coordination."""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn

from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorCredentialRequest,
)
from azents_runtime_control.transfer import (
    RUNTIME_TRANSFER_COORDINATOR_AUDIENCE,
    CoordinatorTransferIdentity,
)

_CREDENTIAL_PREFIX = "ctr1"
_CREDENTIAL_VERSION = "v1"
_DOMAIN_LABEL = b"azents/runtime-transfer-coordinator-credential/v1"
_ROOT_BYTES = 32
_MAX_LIFETIME = timedelta(seconds=60)
_DEFAULT_CLOCK_SKEW = timedelta(seconds=5)
_DEFAULT_ALLOWED_SERVICE_IDENTITIES = frozenset({"azents-api", "azents-worker"})
_INVALID_CREDENTIAL_MESSAGE = "Invalid coordinator credential"


class RuntimeTransferCoordinatorCredentialInvalid(ValueError):
    """Raised when trusted coordinator credential verification fails."""


@dataclass(frozen=True)
class RuntimeTransferCoordinatorCredentialClaims:
    """Authenticated exact scope for one coordinator RPC request."""

    audience: str
    service_identity: str
    operation: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    nonce: str
    identity: CoordinatorTransferIdentity
    request_sha256: str


class RuntimeTransferCoordinatorCredentialVerifier:
    """Issue and verify domain-separated short-lived coordinator credentials."""

    def __init__(
        self,
        credential_encryption_key: str,
        *,
        clock: Callable[[], datetime],
        allowed_service_identities: Collection[str] = (
            _DEFAULT_ALLOWED_SERVICE_IDENTITIES
        ),
        clock_skew: timedelta = _DEFAULT_CLOCK_SKEW,
        maximum_lifetime: timedelta = _MAX_LIFETIME,
    ) -> None:
        """Derive one coordinator-only HMAC key from deployment root material.

        :param credential_encryption_key: deployment-root credential material
        :param clock: timezone-aware clock used for time validation
        :param allowed_service_identities: trusted credential service identities
        :param clock_skew: maximum allowed future issuance or not-before skew
        :param maximum_lifetime: maximum accepted credential validity duration
        :raises ValueError: if root material or verifier configuration is invalid
        """
        try:
            root = base64.b64decode(
                credential_encryption_key.encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
            raise ValueError("Invalid credential encryption key") from exc
        if len(root) != _ROOT_BYTES:
            raise ValueError("Invalid credential encryption key")
        if clock_skew < timedelta():
            raise ValueError("Coordinator credential clock skew must not be negative")
        if not timedelta() < maximum_lifetime <= _MAX_LIFETIME:
            raise ValueError(
                "Coordinator credential maximum lifetime must be within 60 seconds"
            )
        allowed_identities = frozenset(allowed_service_identities)
        if not allowed_identities or any(
            not _valid_text(value, maximum_bytes=128) for value in allowed_identities
        ):
            raise ValueError("Coordinator service identities are required")
        self._key = hmac.new(root, _DOMAIN_LABEL, hashlib.sha256).digest()
        self._clock = clock
        self._allowed_service_identities = allowed_identities
        self._clock_skew = clock_skew
        self._maximum_lifetime = maximum_lifetime

    def issue(
        self,
        claims: RuntimeTransferCoordinatorCredentialClaims,
    ) -> str:
        """Issue a credential scoped to one exact coordinator RPC request.

        :param claims: complete short-lived credential claims
        :returns: signed transport credential
        :raises RuntimeTransferCoordinatorCredentialInvalid: if claims are invalid
        """
        self._validate_claims(claims, now=self._now(), validate_time=True)
        encoded_payload = _encode(_canonical_payload(claims).encode("utf-8"))
        signature = _encode(
            hmac.new(
                self._key,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        return f"{_CREDENTIAL_PREFIX}.{encoded_payload}.{signature}"

    def verify(
        self,
        credential: str,
        *,
        expected_operation: str,
        expected_request_sha256: str,
        expected_identity: CoordinatorTransferIdentity,
    ) -> RuntimeTransferCoordinatorCredentialClaims:
        """Verify a credential against one exact RPC method and request.

        :param credential: bearer credential value without the bearer prefix
        :param expected_operation: exact coordinator RPC operation
        :param expected_request_sha256: canonical deterministic request digest
        :param expected_identity: identity repeated by the protobuf request
        :returns: verified credential claims
        :raises RuntimeTransferCoordinatorCredentialInvalid: if verification fails
        """
        if (
            credential != credential.strip()
            or not expected_operation
            or not _is_sha256(expected_request_sha256)
        ):
            _invalid_credential()
        prefix, encoded_payload, signature = _split_credential(credential)
        if prefix != _CREDENTIAL_PREFIX:
            _invalid_credential()
        expected_signature = _encode(
            hmac.new(
                self._key,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(signature, expected_signature):
            _invalid_credential()
        claims = _claims_from_encoded_payload(encoded_payload)
        self._validate_claims(claims, now=self._now(), validate_time=True)
        if (
            claims.operation != expected_operation
            or not hmac.compare_digest(
                claims.request_sha256,
                expected_request_sha256,
            )
            or claims.identity != expected_identity
        ):
            _invalid_credential()
        return claims

    def _validate_claims(
        self,
        claims: RuntimeTransferCoordinatorCredentialClaims,
        *,
        now: datetime,
        validate_time: bool,
    ) -> None:
        if (
            claims.audience != RUNTIME_TRANSFER_COORDINATOR_AUDIENCE
            or claims.service_identity not in self._allowed_service_identities
            or not _valid_text(claims.operation, maximum_bytes=256)
            or not _valid_nonce(claims.nonce)
            or not _valid_identity(claims.identity)
            or not _is_sha256(claims.request_sha256)
            or not _aware(claims.issued_at)
            or not _aware(claims.not_before)
            or not _aware(claims.expires_at)
            or claims.issued_at > claims.not_before
            or claims.not_before > claims.expires_at
            or claims.expires_at <= claims.issued_at
            or claims.expires_at - claims.issued_at > self._maximum_lifetime
        ):
            _invalid_credential()
        if validate_time and (
            claims.issued_at > now + self._clock_skew
            or claims.not_before > now + self._clock_skew
            or claims.expires_at <= now
        ):
            _invalid_credential()

    def _now(self) -> datetime:
        now = self._clock()
        if not _aware(now):
            raise ValueError("Coordinator credential clock must be timezone-aware")
        return now


@dataclass(frozen=True)
class RuntimeTransferCoordinatorCredentialSupplier:
    """Issue one short-lived coordinator credential immediately before an RPC."""

    verifier: RuntimeTransferCoordinatorCredentialVerifier
    service_identity: str
    clock: Callable[[], datetime]
    lifetime: timedelta

    def __post_init__(self) -> None:
        """Validate explicit caller identity and credential lifetime."""
        if not _valid_text(self.service_identity, maximum_bytes=128):
            raise ValueError("Coordinator service identity is required")
        if not timedelta() < self.lifetime <= _MAX_LIFETIME:
            raise ValueError(
                "Coordinator credential lifetime must be positive and at most "
                "60 seconds"
            )

    async def issue(self, request: CoordinatorCredentialRequest) -> str:
        """Issue a credential bound to one exact shared client request.

        :param request: secret-free exact coordinator request values
        :returns: signed short-lived bearer credential
        :raises ValueError: if the injected clock is not timezone-aware
        """
        issued_at = self.clock()
        if not _aware(issued_at):
            raise ValueError("Coordinator credential clock must be timezone-aware")
        return self.verifier.issue(
            new_coordinator_claims(
                service_identity=self.service_identity,
                operation=request.operation,
                identity=request.identity,
                request_sha256=request.request_sha256,
                issued_at=issued_at,
                not_before=issued_at,
                expires_at=issued_at + self.lifetime,
                nonce=None,
            )
        )


def new_coordinator_claims(
    *,
    service_identity: str,
    operation: str,
    identity: CoordinatorTransferIdentity,
    request_sha256: str,
    issued_at: datetime,
    not_before: datetime,
    expires_at: datetime,
    nonce: str | None,
) -> RuntimeTransferCoordinatorCredentialClaims:
    """Build one explicit short-lived claim set for a canonical request.

    :param service_identity: trusted caller identity
    :param operation: exact coordinator RPC operation
    :param identity: transfer identity bound to the request
    :param request_sha256: canonical request digest
    :param issued_at: credential issuance time
    :param not_before: credential validity start time
    :param expires_at: credential expiration time
    :param nonce: unique caller-supplied nonce, or None to generate one
    :returns: complete unsigned credential claims
    """
    return RuntimeTransferCoordinatorCredentialClaims(
        audience=RUNTIME_TRANSFER_COORDINATOR_AUDIENCE,
        service_identity=service_identity,
        operation=operation,
        issued_at=issued_at,
        not_before=not_before,
        expires_at=expires_at,
        nonce=secrets.token_urlsafe(24) if nonce is None else nonce,
        identity=identity,
        request_sha256=request_sha256,
    )


def _claims_from_encoded_payload(
    encoded_payload: str,
) -> RuntimeTransferCoordinatorCredentialClaims:
    try:
        decoded = _decode(encoded_payload)
        payload = decoded.decode("utf-8")
        value = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
        claims = _claims_from_value(value)
    except (
        UnicodeDecodeError,
        UnicodeEncodeError,
        binascii.Error,
        json.JSONDecodeError,
        ValueError,
    ):
        _invalid_credential()
    if payload != _canonical_payload(claims):
        _invalid_credential()
    return claims


def _claims_from_value(
    value: object,
) -> RuntimeTransferCoordinatorCredentialClaims:
    if not isinstance(value, dict) or not _has_exact_fields(
        value,
        _CLAIM_FIELDS,
    ):
        raise ValueError("Invalid credential payload")
    if value["version"] != _CREDENTIAL_VERSION:
        raise ValueError("Invalid credential payload")
    identity_value = value["identity"]
    if not isinstance(identity_value, dict) or not _has_exact_fields(
        identity_value,
        _IDENTITY_FIELDS,
    ):
        raise ValueError("Invalid credential payload")
    return RuntimeTransferCoordinatorCredentialClaims(
        audience=_text(value["audience"]),
        service_identity=_text(value["service_identity"]),
        operation=_text(value["operation"]),
        issued_at=_timestamp(value["issued_at"]),
        not_before=_timestamp(value["not_before"]),
        expires_at=_timestamp(value["expires_at"]),
        nonce=_text(value["nonce"]),
        identity=CoordinatorTransferIdentity(
            transfer_id=_text(identity_value["transfer_id"]),
            attempt_id=_text(identity_value["attempt_id"]),
            runtime_id=_text(identity_value["runtime_id"]),
            desired_generation=_integer(identity_value["desired_generation"]),
            direction=_text(identity_value["direction"]),
            operation_id=_text(identity_value["operation_id"]),
            session_id=_optional_text(identity_value["session_id"]),
            agent_id=_optional_text(identity_value["agent_id"]),
        ),
        request_sha256=_text(value["request_sha256"]),
    )


def _canonical_payload(
    claims: RuntimeTransferCoordinatorCredentialClaims,
) -> str:
    return json.dumps(
        {
            "audience": claims.audience,
            "expires_at": _timestamp_value(claims.expires_at),
            "identity": {
                "agent_id": claims.identity.agent_id,
                "attempt_id": claims.identity.attempt_id,
                "desired_generation": claims.identity.desired_generation,
                "direction": claims.identity.direction,
                "operation_id": claims.identity.operation_id,
                "runtime_id": claims.identity.runtime_id,
                "session_id": claims.identity.session_id,
                "transfer_id": claims.identity.transfer_id,
            },
            "issued_at": _timestamp_value(claims.issued_at),
            "nonce": claims.nonce,
            "not_before": _timestamp_value(claims.not_before),
            "operation": claims.operation,
            "request_sha256": claims.request_sha256,
            "service_identity": claims.service_identity,
            "version": _CREDENTIAL_VERSION,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _timestamp_value(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _reject_duplicate_keys(
    values: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise ValueError("Duplicate credential payload key")
        result[key] = value
    return result


def _has_exact_fields(
    value: Mapping[object, object],
    expected_fields: frozenset[str],
) -> bool:
    return len(value) == len(expected_fields) and all(
        isinstance(key, str) and key in expected_fields for key in value
    )


def _split_credential(credential: str) -> tuple[str, str, str]:
    parts = credential.split(".")
    if len(parts) != 3 or not all(parts):
        _invalid_credential()
    return parts[0], parts[1], parts[2]


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.b64decode(
        f"{value}{'=' * (-len(value) % 4)}".encode("ascii"),
        altchars=b"-_",
        validate=True,
    )


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Credential text value required")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _text(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Credential integer value required")
    return value


def _timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(_text(value))
    if not _aware(parsed):
        raise ValueError("Timezone-aware timestamp required")
    return parsed


def _valid_identity(value: CoordinatorTransferIdentity) -> bool:
    return (
        _valid_text(value.transfer_id, maximum_bytes=128)
        and _valid_text(value.attempt_id, maximum_bytes=128)
        and _valid_text(value.runtime_id, maximum_bytes=128)
        and value.desired_generation > 0
        and value.direction in {"download", "upload"}
        and _valid_text(value.operation_id, maximum_bytes=128)
        and (
            value.session_id is None or _valid_text(value.session_id, maximum_bytes=128)
        )
        and (value.agent_id is None or _valid_text(value.agent_id, maximum_bytes=128))
    )


def _valid_text(value: str, *, maximum_bytes: int) -> bool:
    return 0 < len(value.encode("utf-8")) <= maximum_bytes


def _valid_nonce(value: str) -> bool:
    return _valid_text(value, maximum_bytes=128) and all(
        character.isascii() and (character.isalnum() or character in {"-", "_"})
        for character in value
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _invalid_credential() -> NoReturn:
    raise RuntimeTransferCoordinatorCredentialInvalid(_INVALID_CREDENTIAL_MESSAGE)


_CLAIM_FIELDS = frozenset(
    {
        "audience",
        "expires_at",
        "identity",
        "issued_at",
        "nonce",
        "not_before",
        "operation",
        "request_sha256",
        "service_identity",
        "version",
    }
)
_IDENTITY_FIELDS = frozenset(
    {
        "agent_id",
        "attempt_id",
        "desired_generation",
        "direction",
        "operation_id",
        "runtime_id",
        "session_id",
        "transfer_id",
    }
)
