"""Validated Runtime Web Gateway process settings."""

import hashlib
import json
import urllib.parse
from pathlib import Path
from typing import Self

from azcommon.logging import RuntimeEnvironment
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from azents.rdb.models.runtime_web import RuntimeWebAuthMode

_IDENTITY_COOKIE_NAME = "__Http-Azents-Runtime-Web"


class RuntimeWebGatewaySettings(BaseSettings):
    """Environment settings for the independent Gateway process."""

    model_config = SettingsConfigDict(
        env_prefix="AZ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    runtime_env: RuntimeEnvironment = RuntimeEnvironment.LOCAL
    sentry_dsn: str | None = None
    runtime_web_gateway_enabled: bool = False
    runtime_web_gateway_port: int = Field(default=8040, ge=1, le=65_535)
    runtime_web_gateway_auth_mode: RuntimeWebAuthMode = RuntimeWebAuthMode.SHARED_COOKIE
    runtime_web_gateway_auth_configuration_version: int = Field(default=1, ge=1)
    runtime_web_gateway_main_web_origin: str | None = None
    runtime_web_gateway_broker_origin: str | None = None
    runtime_web_gateway_service_suffix: str | None = None
    runtime_web_gateway_cookie_domain: str | None = None
    runtime_web_gateway_identity_cookie_name: str = _IDENTITY_COOKIE_NAME
    runtime_web_gateway_identity_lifetime_seconds: int = Field(
        default=1_800,
        ge=60,
        le=3_600,
    )
    runtime_web_gateway_active_duration_seconds: int = Field(
        default=3_600,
        ge=300,
        le=28_800,
    )
    runtime_web_gateway_chromium_min_version: int = Field(default=152, ge=1)
    runtime_web_gateway_chromium_max_version: int = Field(default=152, ge=1)
    runtime_web_gateway_control_endpoint: str | None = None
    runtime_web_gateway_control_allow_insecure: bool = False
    runtime_web_gateway_control_tls_ca_file: Path | None = None
    runtime_web_gateway_control_tls_certificate_file: Path | None = None
    runtime_web_gateway_control_tls_private_key_file: Path | None = None
    runtime_web_gateway_request_header_bytes: int = Field(
        default=32 * 1024,
        ge=4 * 1024,
        le=128 * 1024,
    )
    runtime_web_gateway_request_body_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=64 * 1024,
        le=1024 * 1024 * 1024,
    )
    runtime_web_gateway_frame_bytes: int = Field(
        default=64 * 1024,
        ge=4 * 1024,
        le=64 * 1024,
    )
    runtime_web_gateway_http_endpoint_connections: int = Field(
        default=32,
        ge=1,
        le=128,
    )
    runtime_web_gateway_http_user_connections: int = Field(
        default=64,
        ge=1,
        le=256,
    )
    runtime_web_gateway_http_agent_connections: int = Field(
        default=128,
        ge=1,
        le=512,
    )
    runtime_web_gateway_websocket_endpoint_connections: int = Field(
        default=4,
        ge=1,
        le=16,
    )
    runtime_web_gateway_websocket_user_connections: int = Field(
        default=8,
        ge=1,
        le=32,
    )
    runtime_web_gateway_websocket_agent_connections: int = Field(
        default=16,
        ge=1,
        le=64,
    )
    runtime_web_gateway_security_permissions_policy: str = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    rdb_host: str = "localhost"
    rdb_port: int = 5432
    rdb_user: str = "azents"
    rdb_password: str | None = None
    rdb_db_name: str = "azents"
    rdb_use_iam_auth: bool = False
    rdb_region: str = "us-west-2"
    rdb_ssl_mode: str = "prefer"
    rdb_verbose: bool = False

    @model_validator(mode="after")
    def _validate_gateway(self) -> Self:
        """Reject incomplete or ambiguous public security configuration."""
        if not self.runtime_web_gateway_enabled:
            return self
        required = {
            "main web origin": self.runtime_web_gateway_main_web_origin,
            "broker origin": self.runtime_web_gateway_broker_origin,
            "service suffix": self.runtime_web_gateway_service_suffix,
            "cookie domain": self.runtime_web_gateway_cookie_domain,
            "Control endpoint": self.runtime_web_gateway_control_endpoint,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                "Runtime Web Gateway requires " + ", ".join(sorted(missing))
            )
        if (
            self.runtime_web_gateway_chromium_min_version
            > self.runtime_web_gateway_chromium_max_version
        ):
            raise ValueError("Runtime Web Chromium version range is invalid")
        if self.runtime_web_gateway_identity_cookie_name != _IDENTITY_COOKIE_NAME:
            raise ValueError("Runtime Web identity cookie name is reserved")
        main = _exact_origin(self.runtime_web_gateway_main_web_origin)
        broker = _exact_origin(self.runtime_web_gateway_broker_origin)
        main_hostname = main.hostname
        broker_hostname = broker.hostname
        if main_hostname is None or broker_hostname is None:
            raise ValueError("Runtime Web origin hostname is required")
        suffix = _normalize_suffix(self.runtime_web_gateway_service_suffix)
        cookie_domain = _normalize_cookie_domain(self.runtime_web_gateway_cookie_domain)
        if broker_hostname != f"auth.{suffix}":
            raise ValueError("Runtime Web broker must be auth.<service suffix>")
        if main_hostname == broker_hostname or main_hostname.endswith(f".{suffix}"):
            raise ValueError("Main Web origin must be outside the service parent")
        if self.runtime_web_gateway_auth_mode is RuntimeWebAuthMode.SEPARATE_DOMAIN:
            if cookie_domain != suffix:
                raise ValueError(
                    "Separate-domain Runtime Web cookie domain must equal "
                    "the service suffix"
                )
        elif not (
            _hostname_within(main_hostname, cookie_domain)
            and _hostname_within(suffix, cookie_domain)
        ):
            raise ValueError(
                "Shared-cookie Runtime Web cookie domain must contain Main Web "
                "and the service suffix"
            )
        if (
            self.runtime_env is not RuntimeEnvironment.LOCAL
            or not self.runtime_web_gateway_control_allow_insecure
        ):
            if main.scheme != "https" or broker.scheme != "https":
                raise ValueError("Runtime Web production origins must use HTTPS")
        tls_files = (
            self.runtime_web_gateway_control_tls_ca_file,
            self.runtime_web_gateway_control_tls_certificate_file,
            self.runtime_web_gateway_control_tls_private_key_file,
        )
        if self.runtime_web_gateway_control_allow_insecure:
            if self.runtime_env is not RuntimeEnvironment.LOCAL:
                raise ValueError("Insecure Runtime Web Control transport is local-only")
        elif any(value is None for value in tls_files):
            raise ValueError("Runtime Web Control mTLS files are required")
        return self

    def security_fingerprint(self) -> str:
        """Return the canonical monotonic authentication configuration digest."""
        return runtime_web_security_fingerprint(
            enabled=self.runtime_web_gateway_enabled,
            mode=self.runtime_web_gateway_auth_mode,
            main_web_origin=self.runtime_web_gateway_main_web_origin,
            broker_origin=self.runtime_web_gateway_broker_origin,
            service_suffix=self.runtime_web_gateway_service_suffix,
            cookie_domain=self.runtime_web_gateway_cookie_domain,
            identity_cookie_name=self.runtime_web_gateway_identity_cookie_name,
            chromium_min_version=self.runtime_web_gateway_chromium_min_version,
            chromium_max_version=self.runtime_web_gateway_chromium_max_version,
        )


def runtime_web_security_fingerprint(
    *,
    enabled: bool,
    mode: RuntimeWebAuthMode,
    main_web_origin: str | None,
    broker_origin: str | None,
    service_suffix: str | None,
    cookie_domain: str | None,
    identity_cookie_name: str,
    chromium_min_version: int,
    chromium_max_version: int,
) -> str:
    """Return the canonical security digest shared by API and Gateway."""
    material = {
        "enabled": enabled,
        "mode": mode.value,
        "main_web_origin": main_web_origin,
        "broker_origin": broker_origin,
        "service_suffix": service_suffix,
        "cookie_domain": cookie_domain,
        "identity_cookie_name": identity_cookie_name,
        "chromium_min_version": chromium_min_version,
        "chromium_max_version": chromium_max_version,
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class RuntimeWebGatewayConfig(BaseModel):
    """Runtime configuration consumed by pure Gateway policy."""

    enabled: bool
    auth_mode: RuntimeWebAuthMode
    configuration_version: int
    main_web_origin: str
    broker_origin: str
    service_suffix: str
    cookie_domain: str
    identity_cookie_name: str
    identity_lifetime_seconds: int
    chromium_min_version: int
    chromium_max_version: int
    request_header_bytes: int
    request_body_bytes: int
    frame_bytes: int
    permissions_policy: str

    @classmethod
    def from_settings(
        cls,
        settings: RuntimeWebGatewaySettings,
    ) -> "RuntimeWebGatewayConfig":
        """Create one enabled, normalized Gateway policy configuration."""
        if not settings.runtime_web_gateway_enabled:
            raise ValueError("Runtime Web Gateway is disabled")
        return cls(
            enabled=True,
            auth_mode=settings.runtime_web_gateway_auth_mode,
            configuration_version=(
                settings.runtime_web_gateway_auth_configuration_version
            ),
            main_web_origin=_origin_text(
                _exact_origin(settings.runtime_web_gateway_main_web_origin)
            ),
            broker_origin=_origin_text(
                _exact_origin(settings.runtime_web_gateway_broker_origin)
            ),
            service_suffix=_normalize_suffix(
                settings.runtime_web_gateway_service_suffix
            ),
            cookie_domain=_normalize_cookie_domain(
                settings.runtime_web_gateway_cookie_domain
            ),
            identity_cookie_name=settings.runtime_web_gateway_identity_cookie_name,
            identity_lifetime_seconds=(
                settings.runtime_web_gateway_identity_lifetime_seconds
            ),
            chromium_min_version=settings.runtime_web_gateway_chromium_min_version,
            chromium_max_version=settings.runtime_web_gateway_chromium_max_version,
            request_header_bytes=settings.runtime_web_gateway_request_header_bytes,
            request_body_bytes=settings.runtime_web_gateway_request_body_bytes,
            frame_bytes=settings.runtime_web_gateway_frame_bytes,
            permissions_policy=(
                settings.runtime_web_gateway_security_permissions_policy
            ),
        )


def _exact_origin(value: str | None) -> urllib.parse.ParseResult:
    if value is None:
        raise ValueError("Runtime Web origin is required")
    parsed = urllib.parse.urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Runtime Web origin must be an exact HTTP(S) origin")
    return parsed


def _origin_text(origin: urllib.parse.ParseResult) -> str:
    host = origin.hostname
    if host is None:
        raise ValueError("Runtime Web origin hostname is required")
    default_port = 443 if origin.scheme == "https" else 80
    port = origin.port
    if port is None or port == default_port:
        return f"{origin.scheme}://{host}"
    return f"{origin.scheme}://{host}:{port}"


def _normalize_suffix(value: str | None) -> str:
    if value is None:
        raise ValueError("Runtime Web service suffix is required")
    suffix = value.strip().lower().rstrip(".")
    if suffix.startswith("."):
        suffix = suffix[1:]
    labels = suffix.split(".")
    if len(labels) < 2 or any(not _valid_dns_label(label) for label in labels):
        raise ValueError("Runtime Web service suffix is invalid")
    return suffix


def _normalize_cookie_domain(value: str | None) -> str:
    if value is None:
        raise ValueError("Runtime Web cookie domain is required")
    return value.strip().lower().lstrip(".").rstrip(".")


def _hostname_within(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def _valid_dns_label(value: str) -> bool:
    return (
        1 <= len(value) <= 63
        and value[0].isalnum()
        and value[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in value)
    )
