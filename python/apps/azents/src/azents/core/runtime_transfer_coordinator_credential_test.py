"""Runtime transfer coordinator credential tests."""

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorCredentialRequest,
)
from azents_runtime_control.transfer import CoordinatorTransferIdentity
from cryptography.fernet import Fernet

from azents.core.runtime_runner_credential import RuntimeRunnerCredentialVerifier
from azents.core.runtime_transfer_coordinator_credential import (
    RuntimeTransferCoordinatorCredentialClaims,
    RuntimeTransferCoordinatorCredentialInvalid,
    RuntimeTransferCoordinatorCredentialSupplier,
    RuntimeTransferCoordinatorCredentialVerifier,
    new_coordinator_claims,
)

_DOMAIN_LABEL = b"azents/runtime-transfer-coordinator-credential/v1"
_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
_DIGEST = "a" * 64
_OPERATION = "RuntimeTransferCoordinator/DispatchTransfer"


def _identity() -> CoordinatorTransferIdentity:
    return CoordinatorTransferIdentity(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=2,
        direction="download",
        operation_id="operation-1",
        session_id="session-1",
        agent_id="agent-1",
    )


def test_issue_and_verify_binds_exact_request_scope() -> None:
    verifier = _verifier()
    claims = _claims()

    credential = verifier.issue(claims)

    assert credential.startswith("ctr1.")
    assert (
        verifier.verify(
            credential,
            expected_operation=_OPERATION,
            expected_request_sha256=_DIGEST,
            expected_identity=_identity(),
        )
        == claims
    )


@pytest.mark.parametrize(
    "expected_operation,expected_digest,identity_factory",
    [
        (
            "RuntimeTransferCoordinator/MarkTransferReady",
            _DIGEST,
            _identity,
        ),
        (_OPERATION, "b" * 64, _identity),
        (
            _OPERATION,
            _DIGEST,
            lambda: CoordinatorTransferIdentity(
                transfer_id="transfer-2",
                attempt_id="attempt-1",
                runtime_id="runtime-1",
                desired_generation=2,
                direction="download",
                operation_id="operation-1",
                session_id="session-1",
                agent_id="agent-1",
            ),
        ),
    ],
)
def test_verify_rejects_operation_digest_or_identity_mismatch(
    expected_operation: str,
    expected_digest: str,
    identity_factory: Callable[[], CoordinatorTransferIdentity],
) -> None:
    verifier = _verifier()
    credential = verifier.issue(_claims())

    with pytest.raises(RuntimeTransferCoordinatorCredentialInvalid):
        verifier.verify(
            credential,
            expected_operation=expected_operation,
            expected_request_sha256=expected_digest,
            expected_identity=identity_factory(),
        )


def test_verify_rejects_runner_credential() -> None:
    root = Fernet.generate_key().decode()
    coordinator_verifier = _verifier(root)
    runner_credential = RuntimeRunnerCredentialVerifier(root).issue(
        runtime_id="runtime-1",
        desired_generation=2,
    )

    with pytest.raises(RuntimeTransferCoordinatorCredentialInvalid):
        coordinator_verifier.verify(
            runner_credential.token,
            expected_operation=_OPERATION,
            expected_request_sha256=_DIGEST,
            expected_identity=_identity(),
        )


@pytest.mark.parametrize("part_index", [0, 1, 2])
def test_verify_rejects_tampered_token(part_index: int) -> None:
    verifier = _verifier()
    parts = verifier.issue(_claims()).split(".")
    parts[part_index] = f"{parts[part_index]}x"

    with pytest.raises(RuntimeTransferCoordinatorCredentialInvalid):
        verifier.verify(
            ".".join(parts),
            expected_operation=_OPERATION,
            expected_request_sha256=_DIGEST,
            expected_identity=_identity(),
        )


@pytest.mark.parametrize(
    "credential",
    [
        "",
        " ctr1.invalid.signature ",
        "ctr1.invalid",
        "ctr1.***.signature",
        "v1.credential.payload.signature",
    ],
)
def test_verify_rejects_malformed_credentials(credential: str) -> None:
    with pytest.raises(RuntimeTransferCoordinatorCredentialInvalid):
        _verifier().verify(
            credential,
            expected_operation=_OPERATION,
            expected_request_sha256=_DIGEST,
            expected_identity=_identity(),
        )


def test_verify_rejects_signed_noncanonical_json_payload() -> None:
    root = Fernet.generate_key().decode()
    verifier = _verifier(root)
    credential = verifier.issue(_claims())
    _prefix, encoded_payload, _signature = credential.split(".")
    payload = _decode(encoded_payload)
    noncanonical = json.dumps(json.loads(payload), sort_keys=False)
    token = _signed_token(root, noncanonical)

    with pytest.raises(RuntimeTransferCoordinatorCredentialInvalid):
        verifier.verify(
            token,
            expected_operation=_OPERATION,
            expected_request_sha256=_DIGEST,
            expected_identity=_identity(),
        )


def test_verify_rejects_expired_and_not_yet_valid_credentials() -> None:
    root = Fernet.generate_key().decode()
    expired_issuer = _verifier(root, now=_NOW)
    expired = expired_issuer.issue(_claims(expires_at=_NOW + timedelta(seconds=1)))
    expired_verifier = _verifier(root, now=_NOW + timedelta(seconds=1))

    with pytest.raises(RuntimeTransferCoordinatorCredentialInvalid):
        _verify(expired_verifier, expired)

    future = _NOW + timedelta(seconds=6)
    future_issuer = _verifier(root, now=future)
    not_yet_valid = future_issuer.issue(
        _claims(
            issued_at=future,
            not_before=future,
            expires_at=future + timedelta(seconds=30),
        )
    )
    current_verifier = _verifier(root, now=_NOW)

    with pytest.raises(RuntimeTransferCoordinatorCredentialInvalid):
        _verify(current_verifier, not_yet_valid)


@pytest.mark.parametrize(
    "claims_factory",
    [
        lambda: _claims(expires_at=_NOW + timedelta(seconds=61)),
        lambda: _claims(
            issued_at=_NOW,
            not_before=_NOW,
            expires_at=_NOW,
        ),
        lambda: _claims(service_identity="untrusted-service"),
    ],
)
def test_issue_rejects_invalid_lifetime_or_service(
    claims_factory: Callable[[], RuntimeTransferCoordinatorCredentialClaims],
) -> None:
    with pytest.raises(RuntimeTransferCoordinatorCredentialInvalid):
        _verifier().issue(claims_factory())


def test_verifier_rejects_naive_clock_and_invalid_root() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _verifier(now=datetime(2026, 7, 25, 12, 0)).issue(_claims())
    with pytest.raises(ValueError, match="credential encryption key"):
        RuntimeTransferCoordinatorCredentialVerifier(
            "invalid",
            clock=lambda: _NOW,
        )


@pytest.mark.asyncio
async def test_supplier_issues_a_short_lived_exact_request_credential() -> None:
    verifier = _verifier()
    supplier = RuntimeTransferCoordinatorCredentialSupplier(
        verifier=verifier,
        service_identity="azents-worker",
        clock=lambda: _NOW,
        lifetime=timedelta(seconds=30),
    )
    request = CoordinatorCredentialRequest(
        operation=_OPERATION,
        identity=_identity(),
        request_sha256=_DIGEST,
    )

    credential = await supplier.issue(request)

    claims = verifier.verify(
        credential,
        expected_operation=_OPERATION,
        expected_request_sha256=_DIGEST,
        expected_identity=_identity(),
    )
    assert claims.service_identity == "azents-worker"
    assert claims.expires_at == _NOW + timedelta(seconds=30)


@pytest.mark.parametrize(
    "lifetime",
    [timedelta(), timedelta(seconds=61)],
)
def test_supplier_rejects_nonpositive_or_overlong_lifetime(
    lifetime: timedelta,
) -> None:
    with pytest.raises(ValueError, match="lifetime"):
        RuntimeTransferCoordinatorCredentialSupplier(
            verifier=_verifier(),
            service_identity="azents-api",
            clock=lambda: _NOW,
            lifetime=lifetime,
        )


def _verifier(
    root: str | None = None,
    *,
    now: datetime = _NOW,
) -> RuntimeTransferCoordinatorCredentialVerifier:
    return RuntimeTransferCoordinatorCredentialVerifier(
        root or Fernet.generate_key().decode(),
        clock=lambda: now,
    )


def _claims(
    *,
    service_identity: str = "azents-api",
    issued_at: datetime = _NOW,
    not_before: datetime = _NOW,
    expires_at: datetime = _NOW + timedelta(seconds=30),
) -> RuntimeTransferCoordinatorCredentialClaims:
    return new_coordinator_claims(
        service_identity=service_identity,
        operation=_OPERATION,
        identity=_identity(),
        request_sha256=_DIGEST,
        issued_at=issued_at,
        not_before=not_before,
        expires_at=expires_at,
        nonce="nonce-1",
    )


def _verify(
    verifier: RuntimeTransferCoordinatorCredentialVerifier,
    credential: str,
) -> None:
    verifier.verify(
        credential,
        expected_operation=_OPERATION,
        expected_request_sha256=_DIGEST,
        expected_identity=_identity(),
    )


def _signed_token(root: str, payload: str) -> str:
    key = hmac.new(
        base64.urlsafe_b64decode(root.encode()),
        _DOMAIN_LABEL,
        hashlib.sha256,
    ).digest()
    encoded_payload = _encode(payload.encode())
    signature = _encode(
        hmac.new(key, encoded_payload.encode(), hashlib.sha256).digest()
    )
    return f"ctr1.{encoded_payload}.{signature}"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> str:
    return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}").decode()
