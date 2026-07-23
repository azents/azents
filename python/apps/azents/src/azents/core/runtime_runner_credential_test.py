"""Runtime Runner credential primitive tests."""

import pytest
from cryptography.fernet import Fernet

from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredentialInvalid,
    RuntimeRunnerCredentialVerifier,
)


def _verifier(key: str | None = None) -> RuntimeRunnerCredentialVerifier:
    return RuntimeRunnerCredentialVerifier(key or Fernet.generate_key().decode())


def test_issue_and_verify_binds_runtime_generation_and_identifier() -> None:
    verifier = _verifier()

    issued = verifier.issue(runtime_id="runtime-1", desired_generation=3)

    claims = verifier.verify(issued.token)
    assert (
        verifier.credential_id(runtime_id="runtime-1", desired_generation=3)
        == issued.credential_id
    )
    assert claims.credential_id == issued.credential_id
    assert claims.runtime_id == "runtime-1"
    assert claims.desired_generation == 3
    assert issued.token != issued.credential_id


def test_issue_is_stable_for_runtime_generation_and_root() -> None:
    key = Fernet.generate_key().decode()

    first = _verifier(key).issue(runtime_id="runtime-1", desired_generation=3)
    second = _verifier(key).issue(runtime_id="runtime-1", desired_generation=3)

    assert first == second


def test_issue_changes_when_runtime_or_generation_changes() -> None:
    verifier = _verifier()

    current = verifier.issue(runtime_id="runtime-1", desired_generation=3)
    next_generation = verifier.issue(runtime_id="runtime-1", desired_generation=4)
    another_runtime = verifier.issue(runtime_id="runtime-2", desired_generation=3)

    assert current != next_generation
    assert current != another_runtime


@pytest.mark.parametrize("part_index", [1, 2, 3, 4])
def test_verify_rejects_tampered_credential(part_index: int) -> None:
    verifier = _verifier()
    issued = verifier.issue(runtime_id="runtime-1", desired_generation=3)
    parts = issued.token.split(".")
    parts[part_index] = f"{parts[part_index]}x"

    with pytest.raises(RuntimeRunnerCredentialInvalid):
        verifier.verify(".".join(parts))


def test_verify_rejects_token_from_another_root() -> None:
    issued = _verifier().issue(runtime_id="runtime-1", desired_generation=3)

    with pytest.raises(RuntimeRunnerCredentialInvalid):
        _verifier().verify(issued.token)


@pytest.mark.parametrize(
    "token",
    [
        "",
        " v1.invalid ",
        "v2.credential.cnVudGltZS0x.1.signature",
        "v1.invalid",
        "v1.credential.***.1.signature",
        "v1.credential.cnVudGltZS0x.01.signature",
        "v1.credential.cnVudGltZS0x.-1.signature",
    ],
)
def test_verify_rejects_malformed_credentials(token: str) -> None:
    with pytest.raises(RuntimeRunnerCredentialInvalid):
        _verifier().verify(token)


@pytest.mark.parametrize(
    ("runtime_id", "desired_generation"),
    [("", 1), ("runtime-1", -1)],
)
def test_issue_rejects_invalid_claims(
    runtime_id: str,
    desired_generation: int,
) -> None:
    with pytest.raises(ValueError):
        _verifier().issue(
            runtime_id=runtime_id,
            desired_generation=desired_generation,
        )


def test_verifier_rejects_invalid_root_key() -> None:
    with pytest.raises(ValueError):
        RuntimeRunnerCredentialVerifier("not-a-fernet-key")
