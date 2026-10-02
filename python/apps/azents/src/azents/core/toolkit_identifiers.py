"""Canonical Toolkit Name and Slug materialization."""

import dataclasses
import re
import unicodedata
from typing import Literal

TOOLKIT_SLUG_PATTERN = r"^[a-z0-9_]+$"
TOOLKIT_SLUG_MAX_LENGTH = 100

_TOOLKIT_WHITESPACE = (
    "\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
)
_TRIM_PATTERN = re.compile(rf"^[{_TOOLKIT_WHITESPACE}]+|[{_TOOLKIT_WHITESPACE}]+$")
_DEFAULT_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")
_EXPLICIT_SEPARATOR_PATTERN = re.compile(rf"[{_TOOLKIT_WHITESPACE}-]+")
_UNDERSCORE_PATTERN = re.compile(r"_+")
_VALID_SLUG_PATTERN = re.compile(TOOLKIT_SLUG_PATTERN)


@dataclasses.dataclass(frozen=True)
class IdentifierValidationError:
    """Field-scoped Toolkit identifier validation failure."""

    field: Literal["name", "slug"]
    detail: str


@dataclasses.dataclass(frozen=True)
class ResolvedToolkitIdentifiers:
    """Materialized non-null Toolkit identifiers."""

    name: str
    slug: str


def trim_toolkit_whitespace(value: str) -> str:
    """Trim the language-neutral whitespace set used by identifier policy."""
    return _TRIM_PATTERN.sub("", value)


def resolve_toolkit_name(
    toolkit_type: str,
    canonical_name: str,
    submitted_name: str | None,
) -> str | IdentifierValidationError:
    """Resolve one submitted Toolkit Name."""
    normalized = (
        trim_toolkit_whitespace(submitted_name) if submitted_name is not None else ""
    )
    if normalized:
        return normalized
    if toolkit_type == "mcp":
        return IdentifierValidationError(
            field="name",
            detail="Name is required for generic MCP Toolkits.",
        )
    return canonical_name


def slugify_toolkit_name(value: str) -> str:
    """Derive a Toolkit Slug from a display Name."""
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    normalized = _DEFAULT_SEPARATOR_PATTERN.sub("_", ascii_value.lower()).strip("_")
    return normalized[:TOOLKIT_SLUG_MAX_LENGTH].rstrip("_")


def resolve_default_toolkit_slug(effective_name: str, canonical_name: str) -> str:
    """Resolve a default Slug, falling back to the canonical Provider Name."""
    slug = slugify_toolkit_name(effective_name)
    if slug:
        return slug
    fallback = slugify_toolkit_name(canonical_name)
    if not fallback:
        raise RuntimeError("Toolkit Provider canonical Name cannot produce a Slug.")
    return fallback


def normalize_explicit_toolkit_slug(
    submitted_slug: str,
) -> str | None | IdentifierValidationError:
    """Normalize an explicit Slug, returning None when blank requests a reset."""
    trimmed = trim_toolkit_whitespace(submitted_slug)
    if not trimmed:
        return None
    ascii_lowered = "".join(
        chr(ord(character) + 32) if "A" <= character <= "Z" else character
        for character in trimmed
    )
    normalized = _EXPLICIT_SEPARATOR_PATTERN.sub("_", ascii_lowered)
    normalized = _UNDERSCORE_PATTERN.sub("_", normalized)
    if (
        len(normalized) > TOOLKIT_SLUG_MAX_LENGTH
        or _VALID_SLUG_PATTERN.fullmatch(normalized) is None
    ):
        return IdentifierValidationError(
            field="slug",
            detail=(
                "Slug must contain at most 100 lowercase ASCII letters, numbers, "
                "or underscores."
            ),
        )
    return normalized


def resolve_create_identifiers(
    *,
    toolkit_type: str,
    canonical_name: str,
    submitted_name: str | None,
    submitted_slug: str | None,
) -> ResolvedToolkitIdentifiers | IdentifierValidationError:
    """Resolve non-null identifiers for Toolkit creation."""
    name = resolve_toolkit_name(toolkit_type, canonical_name, submitted_name)
    if isinstance(name, IdentifierValidationError):
        return name
    normalized_slug = (
        None
        if submitted_slug is None
        else normalize_explicit_toolkit_slug(submitted_slug)
    )
    if isinstance(normalized_slug, IdentifierValidationError):
        return normalized_slug
    slug = (
        resolve_default_toolkit_slug(name, canonical_name)
        if normalized_slug is None
        else normalized_slug
    )
    return ResolvedToolkitIdentifiers(name=name, slug=slug)
