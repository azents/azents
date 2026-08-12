"""Canonical proxy policy tests."""

import json

import pytest

from azents_runtime_provider_kubernetes.proxy_policy import (
    PROXY_POLICY_SCHEMA_VERSION,
    ProxyDomainMode,
    ProxyPolicyInput,
    canonical_proxy_policy,
)

_DIGEST = "a" * 64


def _input(
    *,
    allowed_domains: tuple[str, ...] = ("api.example.com", "*.example.org"),
    denied_domains: tuple[str, ...] = ("blocked.example.com",),
    allowed_cidrs: tuple[str, ...] = ("203.0.113.0/24", "2001:db8::/32"),
    denied_cidrs: tuple[str, ...] = ("203.0.113.128/25",),
    domain_mode: ProxyDomainMode = ProxyDomainMode.ALLOWLIST,
) -> ProxyPolicyInput:
    return ProxyPolicyInput(
        runtime_id="runtime-1",
        configuration_sequence=3,
        configuration_digest=_DIGEST,
        domain_mode=domain_mode,
        allowed_domains=allowed_domains,
        denied_domains=denied_domains,
        allowed_cidrs=allowed_cidrs,
        denied_cidrs=denied_cidrs,
        ca_fingerprint="b" * 64,
        artifact_digest="c" * 64,
    )


def test_proxy_policy_is_canonical_and_order_independent() -> None:
    first = canonical_proxy_policy(_input())
    second = canonical_proxy_policy(
        _input(
            allowed_domains=("*.example.org", "api.example.com"),
            allowed_cidrs=("2001:db8::/32", "203.0.113.0/24"),
        )
    )

    assert first == second
    assert " " not in first.document
    document = json.loads(first.document)
    assert document == {
        "schema_version": PROXY_POLICY_SCHEMA_VERSION,
        "runtime_id": "runtime-1",
        "configuration_sequence": 3,
        "configuration_digest": _DIGEST,
        "domain_policy": {
            "mode": "allowlist",
            "allowed_domains": ["*.example.org", "api.example.com"],
            "denied_domains": ["blocked.example.com"],
        },
        "network_policy": {
            "allowed_cidrs": ["2001:db8::/32", "203.0.113.0/24"],
            "denied_cidrs": ["203.0.113.128/25"],
        },
        "ca_fingerprint": "b" * 64,
        "artifact_digest": "c" * 64,
    }


def test_proxy_policy_rejects_noncanonical_or_invalid_authority() -> None:
    with pytest.raises(ValueError, match="canonical"):
        canonical_proxy_policy(_input(allowed_domains=("Example.COM",)))
    with pytest.raises(ValueError, match="host bits"):
        canonical_proxy_policy(_input(allowed_cidrs=("203.0.113.1/24",)))
    with pytest.raises(ValueError, match="unrestricted"):
        canonical_proxy_policy(_input(domain_mode=ProxyDomainMode.UNRESTRICTED))


def test_unrestricted_proxy_policy_requires_empty_allowlist() -> None:
    policy = canonical_proxy_policy(
        _input(
            domain_mode=ProxyDomainMode.UNRESTRICTED,
            allowed_domains=(),
        )
    )

    assert json.loads(policy.document)["domain_policy"]["mode"] == "unrestricted"
