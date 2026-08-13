"""Proxy policy parsing and authorization tests."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from azents_runtime_proxy.policy import (
    InvalidProxyPolicy,
    ProxyDomainMode,
    load_proxy_policy,
    parse_proxy_policy,
)


def _document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "runtime_id": "runtime-1",
        "configuration_sequence": 4,
        "configuration_digest": "a" * 64,
        "domain_policy": {
            "mode": "allowlist",
            "allowed_domains": ["*.example.org", "api.example.com"],
            "denied_domains": ["blocked.example.org"],
        },
        "network_policy": {
            "allowed_cidrs": ["2001:db8::/32", "203.0.113.0/24"],
            "denied_cidrs": ["203.0.113.128/25"],
        },
        "ca_fingerprint": "b" * 64,
        "artifact_digest": "c" * 64,
    }


def test_domain_and_cidr_authorization_are_deny_first() -> None:
    policy = parse_proxy_policy(_document(), digest="d" * 64)

    assert policy.domain_mode is ProxyDomainMode.ALLOWLIST
    assert policy.authorize_host("API.EXAMPLE.COM.") == "api.example.com"
    assert policy.authorize_host("sub.example.org") == "sub.example.org"
    with pytest.raises(InvalidProxyPolicy, match="denied"):
        policy.authorize_host("blocked.example.org")
    with pytest.raises(InvalidProxyPolicy, match="allowlist"):
        policy.authorize_host("example.org")
    with pytest.raises(InvalidProxyPolicy, match="IP address"):
        policy.authorize_host("203.0.113.7")
    assert policy.authorize_addresses(("203.0.113.7", "2001:db8::7")) == (
        "203.0.113.7",
        "2001:db8::7",
    )
    with pytest.raises(InvalidProxyPolicy, match="denied"):
        policy.authorize_addresses(("203.0.113.7", "203.0.113.200"))


def test_empty_cidr_allowlist_is_unrestricted_before_denials() -> None:
    document = _document()
    document["domain_policy"] = {
        "mode": "unrestricted",
        "allowed_domains": [],
        "denied_domains": [],
    }
    document["network_policy"] = {
        "allowed_cidrs": [],
        "denied_cidrs": ["203.0.113.128/25"],
    }
    policy = parse_proxy_policy(document, digest="d" * 64)

    assert policy.authorize_host("198.51.100.10") == "198.51.100.10"
    assert policy.authorize_address("198.51.100.10") == "198.51.100.10"


def test_policy_parser_rejects_unknown_and_noncanonical_fields() -> None:
    document = _document()
    document["unknown"] = True
    with pytest.raises(InvalidProxyPolicy, match="fields"):
        parse_proxy_policy(document, digest="d" * 64)

    document = _document()
    document["domain_policy"] = {
        "mode": "allowlist",
        "allowed_domains": ["api.example.com", "*.example.org"],
        "denied_domains": ["blocked.example.org"],
    }
    with pytest.raises(InvalidProxyPolicy, match="sorted"):
        parse_proxy_policy(document, digest="d" * 64)


def test_policy_loader_verifies_canonical_digest_artifact_and_ca(
    tmp_path: Path,
) -> None:
    certificate_path, fingerprint = _certificate(tmp_path)
    document = _document()
    document["ca_fingerprint"] = fingerprint
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"))
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(raw, encoding="utf-8")
    digest = hashlib.sha256(raw.encode()).hexdigest()

    policy = load_proxy_policy(
        policy_path,
        expected_policy_digest=digest,
        expected_artifact_digest="c" * 64,
        public_ca_path=certificate_path,
    )

    assert policy.digest == digest
    with pytest.raises(InvalidProxyPolicy, match="policy digest"):
        load_proxy_policy(
            policy_path,
            expected_policy_digest="e" * 64,
            expected_artifact_digest="c" * 64,
            public_ca_path=certificate_path,
        )


def _certificate(tmp_path: Path) -> tuple[Path, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name((x509.NameAttribute(NameOID.COMMON_NAME, "test-ca"),))
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime(2026, 1, 1, tzinfo=UTC))
        .not_valid_after(datetime(2027, 1, 1, tzinfo=UTC))
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "ca.crt"
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    fingerprint = hashlib.sha256(
        certificate.public_bytes(serialization.Encoding.DER)
    ).hexdigest()
    return path, fingerprint
