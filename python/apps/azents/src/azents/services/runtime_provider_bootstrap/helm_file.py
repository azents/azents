"""Helm-file adapter for authoritative Runtime Provider bootstrap declarations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderKind,
)

from .data import (
    RuntimeProviderBootstrapDeclarationInput,
    RuntimeProviderBootstrapSnapshot,
)

_API_VERSION = "azents.io/v1"
_DOCUMENT_KEYS = frozenset({"apiVersion", "source", "providers"})
_SOURCE_KEYS = frozenset({"key", "revision", "digest"})
_PROVIDER_KEYS = frozenset({"declarationKey", "providerId", "kind", "initial"})
_INITIAL_KEYS = frozenset(
    {
        "displayName",
        "enabled",
        "availabilityMode",
        "setAsPlatformDefaultWhenUnset",
        "capabilities",
        "configSchema",
        "metadata",
    }
)


@dataclass(frozen=True)
class RuntimeProviderBootstrapSourceDocumentError(ValueError):
    """Mounted bootstrap document cannot be used as an authoritative snapshot."""

    source_key: str
    code: str

    def __post_init__(self) -> None:
        ValueError.__init__(
            self,
            f"Runtime Provider bootstrap source document is invalid: {self.code}",
        )


@dataclass(frozen=True)
class HelmFileRuntimeProviderBootstrapAdapter:
    """Read one trusted Helm-rendered non-secret bootstrap document."""

    source_key: str
    path: Path

    async def read_snapshot(self) -> RuntimeProviderBootstrapSnapshot:
        """Read and validate one complete authoritative source snapshot."""
        try:
            document_text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise RuntimeProviderBootstrapSourceDocumentError(
                source_key=self.source_key,
                code="source_file_missing",
            ) from error
        try:
            document = yaml.safe_load(document_text)
        except yaml.YAMLError as error:
            raise RuntimeProviderBootstrapSourceDocumentError(
                source_key=self.source_key,
                code="source_file_malformed",
            ) from error
        try:
            return self._parse_document(document)
        except (TypeError, ValueError) as error:
            if isinstance(error, RuntimeProviderBootstrapSourceDocumentError):
                raise
            raise RuntimeProviderBootstrapSourceDocumentError(
                source_key=self.source_key,
                code="source_file_invalid",
            ) from error

    def _parse_document(self, document: object) -> RuntimeProviderBootstrapSnapshot:
        """Convert a validated Helm document into the adapter-neutral snapshot."""
        root = _mapping(document, "document")
        _assert_exact_keys(root, _DOCUMENT_KEYS, "document")
        if root["apiVersion"] != _API_VERSION:
            raise RuntimeProviderBootstrapSourceDocumentError(
                source_key=self.source_key,
                code="unsupported_api_version",
            )
        source = _mapping(root["source"], "source")
        _assert_exact_keys(source, _SOURCE_KEYS, "source")
        source_key = _string(source["key"], "source.key")
        if source_key != self.source_key:
            raise RuntimeProviderBootstrapSourceDocumentError(
                source_key=self.source_key,
                code="source_key_mismatch",
            )
        providers = _list(root["providers"], "providers")
        declarations = tuple(
            self._parse_declaration(provider, index)
            for index, provider in enumerate(providers)
        )
        return RuntimeProviderBootstrapSnapshot(
            source_key=source_key,
            adapter_kind=RuntimeProviderBootstrapAdapterKind.HELM_FILE,
            source_revision=_string(source["revision"], "source.revision"),
            source_digest=_string(source["digest"], "source.digest"),
            declarations=declarations,
        )

    def _parse_declaration(
        self,
        raw_provider: object,
        index: int,
    ) -> RuntimeProviderBootstrapDeclarationInput:
        """Convert one strict non-secret declaration."""
        provider = _mapping(raw_provider, f"providers[{index}]")
        _assert_exact_keys(provider, _PROVIDER_KEYS, f"providers[{index}]")
        initial = _mapping(provider["initial"], f"providers[{index}].initial")
        _assert_allowed_keys(initial, _INITIAL_KEYS, f"providers[{index}].initial")
        return RuntimeProviderBootstrapDeclarationInput(
            declaration_key=_string(
                provider["declarationKey"],
                f"providers[{index}].declarationKey",
            ),
            provider_logical_id=_string(
                provider["providerId"],
                f"providers[{index}].providerId",
            ),
            kind=RuntimeProviderKind(
                _string(provider["kind"], f"providers[{index}].kind")
            ),
            display_name=_string(
                initial["displayName"],
                f"providers[{index}].initial.displayName",
            ),
            enabled=_bool(initial["enabled"], f"providers[{index}].initial.enabled"),
            availability_mode=RuntimeProviderAvailabilityMode(
                _string(
                    initial["availabilityMode"],
                    f"providers[{index}].initial.availabilityMode",
                )
            ),
            capabilities=(
                _optional_mapping(initial.get("capabilities"), "capabilities") or {}
            ),
            config_schema=_optional_mapping(
                initial.get("configSchema"),
                "configSchema",
            ),
            metadata=_optional_mapping(initial.get("metadata"), "metadata"),
            creation_seeds={
                "set_as_platform_default_when_unset": _bool(
                    initial.get("setAsPlatformDefaultWhenUnset", False),
                    "setAsPlatformDefaultWhenUnset",
                )
            },
        )


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    """Require a mapping with string keys."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field_name} must be a mapping.")
    return value


def _list(value: object, field_name: str) -> list[object]:
    """Require a list value."""
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return value


def _string(value: object, field_name: str) -> str:
    """Require a non-empty string."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value


def _bool(value: object, field_name: str) -> bool:
    """Require a Boolean value without string coercion."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a Boolean.")
    return value


def _optional_mapping(value: object, field_name: str) -> dict[str, Any] | None:
    """Accept an absent/null mapping or reject a different JSON shape."""
    if value is None:
        return None
    return _mapping(value, field_name)


def _assert_exact_keys(
    value: dict[str, Any],
    expected_keys: frozenset[str],
    field_name: str,
) -> None:
    """Require an exact document object shape."""
    if len(value) != len(expected_keys) or any(
        key not in expected_keys for key in value
    ):
        raise ValueError(f"{field_name} has unsupported or missing fields.")


def _assert_allowed_keys(
    value: dict[str, Any],
    allowed_keys: frozenset[str],
    field_name: str,
) -> None:
    """Reject unknown initial fields, including secret-like content."""
    if any(key not in allowed_keys for key in value):
        raise ValueError(f"{field_name} has unsupported fields.")
