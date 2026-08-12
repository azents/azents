"""Strict canonical proxy policy loading and authorization."""

import dataclasses
import enum
import hashlib
import ipaddress
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import serialization

PROXY_POLICY_SCHEMA_VERSION = 1
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "runtime_id",
        "configuration_sequence",
        "configuration_digest",
        "domain_policy",
        "network_policy",
        "ca_fingerprint",
        "artifact_digest",
    }
)
_DOMAIN_POLICY_KEYS = frozenset({"mode", "allowed_domains", "denied_domains"})
_NETWORK_POLICY_KEYS = frozenset({"allowed_cidrs", "denied_cidrs"})


class InvalidProxyPolicy(ValueError):
    """Proxy policy or evidence failed strict validation."""


class ProxyDomainMode(enum.StrEnum):
    """Canonical hostname authority."""

    UNRESTRICTED = "unrestricted"
    ALLOWLIST = "allowlist"


@dataclasses.dataclass(frozen=True)
class ProxyPolicy:
    """Validated policy used by the mitmproxy addon."""

    runtime_id: str
    configuration_sequence: int
    configuration_digest: str
    domain_mode: ProxyDomainMode
    allowed_domains: tuple[str, ...]
    denied_domains: tuple[str, ...]
    allowed_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    denied_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    ca_fingerprint: str
    artifact_digest: str
    digest: str

    def authorize_host(self, host: str) -> str:
        """Return the canonical host when its domain authority permits it."""
        canonical = canonical_host(host)
        try:
            ipaddress.ip_address(canonical)
        except ValueError:
            pass
        else:
            if self.domain_mode is ProxyDomainMode.ALLOWLIST:
                raise InvalidProxyPolicy("destination host must not be an IP address")
            return canonical
        if any(_domain_matches(canonical, item) for item in self.denied_domains):
            raise InvalidProxyPolicy("destination host is denied")
        if self.domain_mode is ProxyDomainMode.ALLOWLIST and not any(
            _domain_matches(canonical, item) for item in self.allowed_domains
        ):
            raise InvalidProxyPolicy("destination host is outside the allowlist")
        return canonical

    def authorize_addresses(
        self,
        addresses: Sequence[str],
    ) -> tuple[str, ...]:
        """Require every resolved address to remain within the CIDR boundary."""
        if not addresses:
            raise InvalidProxyPolicy("destination host resolved no addresses")
        canonical = tuple(
            sorted(
                {str(ipaddress.ip_address(address)) for address in addresses},
                key=lambda item: (
                    ipaddress.ip_address(item).version,
                    ipaddress.ip_address(item).packed,
                ),
            )
        )
        for address in canonical:
            self.authorize_address(address)
        return canonical

    def authorize_address(self, address: str) -> str:
        """Return one canonical selected IP when CIDR authority permits it."""
        candidate = ipaddress.ip_address(address)
        if any(candidate in network for network in self.denied_networks):
            raise InvalidProxyPolicy("destination address is denied")
        if self.allowed_networks and not any(
            candidate in network for network in self.allowed_networks
        ):
            raise InvalidProxyPolicy("destination address is outside the allowlist")
        return str(candidate)


def load_proxy_policy(
    path: Path,
    *,
    expected_policy_digest: str,
    expected_artifact_digest: str,
    public_ca_path: Path,
) -> ProxyPolicy:
    """Load canonical policy and verify every readiness evidence value."""
    raw = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if digest != expected_policy_digest:
        raise InvalidProxyPolicy("proxy policy digest mismatch")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise InvalidProxyPolicy("proxy policy JSON is malformed") from error
    if not isinstance(document, dict):
        raise InvalidProxyPolicy("proxy policy must be an object")
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    if raw != canonical:
        raise InvalidProxyPolicy("proxy policy document is not canonical")
    policy = parse_proxy_policy(document, digest=digest)
    if policy.artifact_digest != expected_artifact_digest:
        raise InvalidProxyPolicy("proxy artifact digest mismatch")
    if certificate_fingerprint(public_ca_path) != policy.ca_fingerprint:
        raise InvalidProxyPolicy("proxy CA fingerprint mismatch")
    return policy


def parse_proxy_policy(document: Mapping[str, Any], *, digest: str) -> ProxyPolicy:
    """Decode already-parsed canonical JSON into the typed policy."""
    _require_exact_keys(document, _TOP_LEVEL_KEYS, "proxy policy")
    if document["schema_version"] != PROXY_POLICY_SCHEMA_VERSION:
        raise InvalidProxyPolicy("unsupported proxy policy schema version")
    runtime_id = _required_string(document["runtime_id"], "runtime_id")
    if _RUNTIME_ID_RE.fullmatch(runtime_id) is None:
        raise InvalidProxyPolicy("runtime_id is invalid")
    configuration_sequence = _required_int(
        document["configuration_sequence"],
        "configuration_sequence",
    )
    if configuration_sequence < 1:
        raise InvalidProxyPolicy("configuration_sequence must be positive")
    configuration_digest = _required_digest(
        document["configuration_digest"],
        "configuration_digest",
    )
    ca_fingerprint = _required_digest(
        document["ca_fingerprint"],
        "ca_fingerprint",
    )
    artifact_digest = _required_digest(
        document["artifact_digest"],
        "artifact_digest",
    )
    domain_policy = _required_mapping(document["domain_policy"], "domain_policy")
    _require_exact_keys(domain_policy, _DOMAIN_POLICY_KEYS, "domain_policy")
    try:
        domain_mode = ProxyDomainMode(
            _required_string(domain_policy["mode"], "domain_policy.mode")
        )
    except ValueError as error:
        raise InvalidProxyPolicy("domain_policy.mode is invalid") from error
    allowed_domains = _required_domains(
        domain_policy["allowed_domains"],
        "domain_policy.allowed_domains",
    )
    denied_domains = _required_domains(
        domain_policy["denied_domains"],
        "domain_policy.denied_domains",
    )
    if domain_mode is ProxyDomainMode.UNRESTRICTED and allowed_domains:
        raise InvalidProxyPolicy(
            "unrestricted domain mode cannot declare allowed domains"
        )
    network_policy = _required_mapping(
        document["network_policy"],
        "network_policy",
    )
    _require_exact_keys(network_policy, _NETWORK_POLICY_KEYS, "network_policy")
    return ProxyPolicy(
        runtime_id=runtime_id,
        configuration_sequence=configuration_sequence,
        configuration_digest=configuration_digest,
        domain_mode=domain_mode,
        allowed_domains=allowed_domains,
        denied_domains=denied_domains,
        allowed_networks=_required_networks(
            network_policy["allowed_cidrs"],
            "network_policy.allowed_cidrs",
        ),
        denied_networks=_required_networks(
            network_policy["denied_cidrs"],
            "network_policy.denied_cidrs",
        ),
        ca_fingerprint=ca_fingerprint,
        artifact_digest=artifact_digest,
        digest=_required_digest(digest, "policy digest"),
    )


def certificate_fingerprint(path: Path) -> str:
    """Return the SHA-256 DER fingerprint for exactly one PEM certificate."""
    raw = path.read_bytes()
    if raw.count(b"-----BEGIN CERTIFICATE-----") != 1:
        raise InvalidProxyPolicy("proxy CA file must contain one certificate")
    try:
        certificate = x509.load_pem_x509_certificate(raw)
    except ValueError as error:
        raise InvalidProxyPolicy("proxy CA certificate is malformed") from error
    return hashlib.sha256(
        certificate.public_bytes(serialization.Encoding.DER)
    ).hexdigest()


def canonical_host(host: str) -> str:
    """Canonicalize one destination hostname without accepting ambiguity."""
    candidate = host.rstrip(".")
    if not candidate:
        raise InvalidProxyPolicy("destination host is empty")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        try:
            ascii_host = candidate.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise InvalidProxyPolicy("destination host is invalid") from error
        labels = ascii_host.split(".")
        if len(ascii_host) > 253 or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in labels
        ):
            raise InvalidProxyPolicy("destination host is invalid") from None
        return ascii_host
    return str(address)


def _domain_matches(host: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return host.endswith(f".{suffix}") and host != suffix
    return host == pattern


def _required_domains(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise InvalidProxyPolicy(f"{field} must be an array")
    result: list[str] = []
    for item in value:
        raw = _required_string(item, field)
        wildcard = raw.startswith("*.")
        candidate = canonical_host(raw[2:] if wildcard else raw)
        canonical = f"*.{candidate}" if wildcard else candidate
        if raw != canonical:
            raise InvalidProxyPolicy(f"{field} must contain canonical patterns")
        result.append(canonical)
    if len(result) != len(set(result)) or result != sorted(result):
        raise InvalidProxyPolicy(f"{field} must be sorted and unique")
    return tuple(result)


def _required_networks(
    value: object,
    field: str,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    if not isinstance(value, list):
        raise InvalidProxyPolicy(f"{field} must be an array")
    result: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in value:
        raw = _required_string(item, field)
        try:
            network = ipaddress.ip_network(raw, strict=True)
        except ValueError as error:
            raise InvalidProxyPolicy(f"{field} contains an invalid CIDR") from error
        if str(network) != raw:
            raise InvalidProxyPolicy(f"{field} must contain canonical CIDRs")
        result.append(network)
    if len(result) != len(set(result)) or [str(item) for item in result] != sorted(
        str(item) for item in result
    ):
        raise InvalidProxyPolicy(f"{field} must be sorted and unique")
    return tuple(result)


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: frozenset[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise InvalidProxyPolicy(f"{field} fields are invalid")


def _required_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise InvalidProxyPolicy(f"{field} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise InvalidProxyPolicy(f"{field} keys must be strings")
    return {str(key): item for key, item in value.items()}


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidProxyPolicy(f"{field} must be a non-empty string")
    return value


def _required_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidProxyPolicy(f"{field} must be an integer")
    return value


def _required_digest(value: object, field: str) -> str:
    digest = _required_string(value, field)
    if _DIGEST_RE.fullmatch(digest) is None:
        raise InvalidProxyPolicy(f"{field} must be a SHA-256 digest")
    return digest
