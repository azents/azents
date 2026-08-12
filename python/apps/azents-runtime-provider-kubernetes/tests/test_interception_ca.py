"""Logical-Runtime interception CA tests."""

from datetime import UTC, datetime

import pytest

from azents_runtime_provider_kubernetes.interception_ca import (
    CA_COMBINED_SECRET_KEY,
    CA_PROFILE_VERSION,
    CA_PUBLIC_SECRET_KEY,
    InvalidRuntimeCa,
    generate_runtime_ca,
    runtime_ca_secret_data,
    validate_runtime_ca,
)

_NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


def test_runtime_ca_generation_round_trips_with_public_private_separation() -> None:
    material = generate_runtime_ca("runtime-1", now=_NOW)

    validated = validate_runtime_ca(
        "runtime-1",
        combined_pem=material.combined_pem,
        public_certificate_pem=material.public_certificate_pem,
        expected_fingerprint=material.fingerprint,
    )
    secret_data = runtime_ca_secret_data(validated)

    assert validated.profile_version == CA_PROFILE_VERSION
    assert validated.fingerprint == material.fingerprint
    assert validated.not_valid_before <= _NOW < validated.not_valid_after
    assert b"PRIVATE KEY" in secret_data[CA_COMBINED_SECRET_KEY]
    assert b"PRIVATE KEY" not in secret_data[CA_PUBLIC_SECRET_KEY]
    assert b"CERTIFICATE" in secret_data[CA_PUBLIC_SECRET_KEY]


def test_runtime_ca_rejects_subject_identity_mismatch() -> None:
    material = generate_runtime_ca("runtime-1", now=_NOW)

    with pytest.raises(InvalidRuntimeCa, match="subject identity mismatch"):
        validate_runtime_ca(
            "runtime-2",
            combined_pem=material.combined_pem,
            public_certificate_pem=material.public_certificate_pem,
            expected_fingerprint=material.fingerprint,
        )


def test_runtime_ca_rejects_key_certificate_mismatch() -> None:
    first = generate_runtime_ca("runtime-1", now=_NOW)
    second = generate_runtime_ca("runtime-1", now=_NOW)
    private_end = first.combined_pem.index(b"-----BEGIN CERTIFICATE-----")
    mismatched = first.combined_pem[:private_end] + second.public_certificate_pem

    with pytest.raises(InvalidRuntimeCa, match="key and certificate mismatch"):
        validate_runtime_ca(
            "runtime-1",
            combined_pem=mismatched,
            public_certificate_pem=second.public_certificate_pem,
            expected_fingerprint=None,
        )


def test_runtime_ca_rejects_public_certificate_and_fingerprint_mismatch() -> None:
    first = generate_runtime_ca("runtime-1", now=_NOW)
    second = generate_runtime_ca("runtime-1", now=_NOW)

    with pytest.raises(InvalidRuntimeCa, match="public certificate mismatch"):
        validate_runtime_ca(
            "runtime-1",
            combined_pem=first.combined_pem,
            public_certificate_pem=second.public_certificate_pem,
            expected_fingerprint=None,
        )
    with pytest.raises(InvalidRuntimeCa, match="fingerprint mismatch"):
        validate_runtime_ca(
            "runtime-1",
            combined_pem=first.combined_pem,
            public_certificate_pem=first.public_certificate_pem,
            expected_fingerprint=second.fingerprint,
        )


def test_runtime_ca_rejects_malformed_existing_state_without_regeneration() -> None:
    with pytest.raises(InvalidRuntimeCa, match="malformed"):
        validate_runtime_ca(
            "runtime-1",
            combined_pem=b"not-a-private-key",
            public_certificate_pem=b"not-a-certificate",
            expected_fingerprint=None,
        )


@pytest.mark.parametrize(
    ("combined_suffix", "public_suffix"),
    [
        (b"unexpected", b""),
        (b"", b"unexpected"),
        (b"", b"\n-----BEGIN CERTIFICATE-----\nextra\n-----END CERTIFICATE-----\n"),
    ],
)
def test_runtime_ca_rejects_unexpected_or_multiple_pem_blocks(
    combined_suffix: bytes,
    public_suffix: bytes,
) -> None:
    material = generate_runtime_ca("runtime-1", now=_NOW)

    with pytest.raises(InvalidRuntimeCa, match="malformed"):
        validate_runtime_ca(
            "runtime-1",
            combined_pem=material.combined_pem + combined_suffix,
            public_certificate_pem=material.public_certificate_pem + public_suffix,
            expected_fingerprint=None,
        )


def test_runtime_ca_generation_requires_utc_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_runtime_ca("runtime-1", now=datetime(2026, 8, 12))
