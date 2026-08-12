"""Canonical proxy policy document and digest."""

import dataclasses
import enum
import hashlib
import ipaddress
import json
import re

from azents_runtime_provider_kubernetes.owned_resources import validate_runtime_id

PROXY_POLICY_SCHEMA_VERSION = 1
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_EXACT_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class ProxyDomainMode(enum.StrEnum):
    """Canonical proxy domain authority."""

    UNRESTRICTED = "unrestricted"
    ALLOWLIST = "allowlist"


@dataclasses.dataclass(frozen=True)
class ProxyPolicyInput:
    """Canonical Provider input for one proxy policy revision."""

    runtime_id: str
    configuration_sequence: int
    configuration_digest: str
    domain_mode: ProxyDomainMode
    allowed_domains: tuple[str, ...]
    denied_domains: tuple[str, ...]
    allowed_cidrs: tuple[str, ...]
    denied_cidrs: tuple[str, ...]
    ca_fingerprint: str
    artifact_digest: str


@dataclasses.dataclass(frozen=True)
class CanonicalProxyPolicy:
    """Deterministic serialized policy and its SHA-256 digest."""

    document: str
    digest: str


def canonical_proxy_policy(value: ProxyPolicyInput) -> CanonicalProxyPolicy:
    """Validate and serialize one proxy policy deterministically."""
    runtime_id = validate_runtime_id(value.runtime_id)
    if value.configuration_sequence < 1:
        raise ValueError("configuration sequence must be greater than zero")
    for name, digest in (
        ("configuration digest", value.configuration_digest),
        ("CA fingerprint", value.ca_fingerprint),
        ("artifact digest", value.artifact_digest),
    ):
        if _DIGEST_RE.fullmatch(digest) is None:
            raise ValueError(f"{name} must be a SHA-256 digest")
    allowed_domains = _canonical_domains(value.allowed_domains)
    denied_domains = _canonical_domains(value.denied_domains)
    if value.domain_mode is ProxyDomainMode.UNRESTRICTED and allowed_domains:
        raise ValueError("unrestricted domain mode cannot contain allowed domains")
    allowed_cidrs = _canonical_cidrs(value.allowed_cidrs)
    denied_cidrs = _canonical_cidrs(value.denied_cidrs)
    document = json.dumps(
        {
            "schema_version": PROXY_POLICY_SCHEMA_VERSION,
            "runtime_id": runtime_id,
            "configuration_sequence": value.configuration_sequence,
            "configuration_digest": value.configuration_digest,
            "domain_policy": {
                "mode": value.domain_mode.value,
                "allowed_domains": list(allowed_domains),
                "denied_domains": list(denied_domains),
            },
            "network_policy": {
                "allowed_cidrs": list(allowed_cidrs),
                "denied_cidrs": list(denied_cidrs),
            },
            "ca_fingerprint": value.ca_fingerprint,
            "artifact_digest": value.artifact_digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return CanonicalProxyPolicy(
        document=document,
        digest=hashlib.sha256(document.encode("utf-8")).hexdigest(),
    )


def _canonical_domains(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value != value.lower() or value.endswith("."):
            raise ValueError("proxy domain patterns must be canonical")
        candidate = value[2:] if value.startswith("*.") else value
        if _EXACT_DOMAIN_RE.fullmatch(candidate) is None:
            raise ValueError("proxy domain pattern is invalid")
        result.append(value)
    if len(result) != len(set(result)):
        raise ValueError("proxy domain patterns must be unique")
    return tuple(sorted(result))


def _canonical_cidrs(values: tuple[str, ...]) -> tuple[str, ...]:
    result = tuple(
        sorted(str(ipaddress.ip_network(value, strict=True)) for value in values)
    )
    if len(result) != len(set(result)):
        raise ValueError("proxy CIDRs must be unique")
    return result
