"""Authored consolidation artifacts and whole, independently bounded unit envelopes."""

import dataclasses
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.historical_memory_consolidation import (
    ConsolidationDisposition,
    ConsolidationScope,
    ConsolidationUnitKey,
)
from azents.core.vfs import VfsUriError, parse_vfs_exact_uri

_CONTEXT_HEADING = "## Historical Context"
_ROUTES_HEADING = "## Source Routes"
_MANAGED_URI = re.compile(r"azents://[^\s<>\[\]()\"'`]+", re.IGNORECASE)
_ROUTE = re.compile(r"^- (azents://\S+) — (\S.*)$")
MAX_CONSOLIDATION_RENDERED_BYTES = 10_000


class ConsolidationOutputError(ValueError):
    """A private authored artifact cannot become a published overview."""


class ConsolidationPublicationUncertainError(RuntimeError):
    """A completed publication scope failed to confirm its database outcome."""


class ConsolidationWorkDisposition(BaseModel):
    """An explicit exact work choice, never an acknowledgement inferred from reads."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    work_id: str = Field(min_length=32, max_length=32)
    action: ConsolidationDisposition
    reason: str = Field(min_length=1, max_length=512)


class ConsolidationCoverage(BaseModel):
    """One bounded publication slice; the finite corpus itself has no size cap."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    dispositions: tuple[ConsolidationWorkDisposition, ...]

    @model_validator(mode="after")
    def unique_work(self) -> "ConsolidationCoverage":
        """Reject conflicting or duplicate claims before any journal mutation."""
        if len({item.work_id for item in self.dispositions}) != len(self.dispositions):
            raise ValueError("Consolidation coverage repeats a work identity.")
        return self


@dataclasses.dataclass(frozen=True)
class ConsolidationSourceRoute:
    """One canonical exact-scoped locator declared with meaningful retrieval text."""

    source_session_id: str
    uri: str
    description: str


@dataclasses.dataclass(frozen=True)
class ValidatedConsolidationOverview:
    """Complete publishable bytes, without model-controlled identity or framing."""

    markdown: str
    rendered_block: str
    routes: tuple[ConsolidationSourceRoute, ...]
    empty: bool


def _route_source_id(uri: str, key: ConsolidationUnitKey) -> str:
    try:
        location = parse_vfs_exact_uri(uri)
    except VfsUriError:
        raise ConsolidationOutputError(
            "Consolidation source route is invalid."
        ) from None
    parts = location.path.removeprefix("/").split("/")
    if (
        location.mount != "memory"
        or len(parts) != 4
        or parts[0] != "historical"
        or parts[1] != key.scope.value
        or len(parts[2]) != 32
        or any(character not in "0123456789abcdef" for character in parts[2])
        or parts[3] != "summary.md"
    ):
        raise ConsolidationOutputError("Consolidation source route is unavailable.")
    return parts[2]


def consolidation_envelope(key: ConsolidationUnitKey, markdown: str) -> str:
    """Allocate every byte to this unit without peer hints or outer framing."""
    scope = "Team" if key.scope is ConsolidationScope.TEAM else "Personal"
    return (
        "HISTORICAL MEMORY DATA BEGINS\n"
        f"Scope: {scope}; Agent: {key.agent_id}; Workspace: {key.workspace_id}\n"
        "Source-dependent historical data may be incomplete, stale, or wrong.\n"
        "Current instructions and verified current evidence take precedence.\n"
        "Source routes are retrieval references, not independent corroboration.\n\n"
        f"{markdown}\n"
        "HISTORICAL MEMORY DATA ENDS\n"
    )


def validate_consolidation_overview(
    *, key: ConsolidationUnitKey, markdown: str
) -> ValidatedConsolidationOverview:
    """Validate sections and every managed locator, then bound the whole envelope."""
    try:
        markdown.encode("utf-8")
    except UnicodeEncodeError:
        raise ConsolidationOutputError(
            "Consolidation Markdown must be UTF-8."
        ) from None
    if "\x00" in markdown:
        raise ConsolidationOutputError("Consolidation Markdown payload is invalid.")
    lines = markdown.splitlines()
    context_positions = [
        index for index, line in enumerate(lines) if line == _CONTEXT_HEADING
    ]
    route_positions = [
        index for index, line in enumerate(lines) if line == _ROUTES_HEADING
    ]
    if (
        len(context_positions) != 1
        or len(route_positions) != 1
        or context_positions[0] >= route_positions[0]
        or any(line.strip() for line in lines[: context_positions[0]])
    ):
        raise ConsolidationOutputError(
            "Consolidation Markdown requires Historical Context then Source Routes."
        )
    context = "\n".join(lines[context_positions[0] + 1 : route_positions[0]]).strip()
    routes: list[ConsolidationSourceRoute] = []
    for line in lines[route_positions[0] + 1 :]:
        if not line.strip():
            continue
        matched = _ROUTE.fullmatch(line)
        if matched is None:
            raise ConsolidationOutputError(
                "Each source route requires a canonical summary URI and description."
            )
        uri, description = matched.groups()
        routes.append(
            ConsolidationSourceRoute(
                _route_source_id(uri, key), uri, description.strip()
            )
        )
    declared = {route.uri for route in routes}
    if len(declared) != len(routes):
        raise ConsolidationOutputError(
            "Consolidation source routes repeat an identity."
        )
    for locator in _MANAGED_URI.findall(markdown):
        _route_source_id(locator, key)
        if locator not in declared:
            raise ConsolidationOutputError(
                "Consolidation locator lacks a declared source route."
            )
    if not context and not routes:
        return ValidatedConsolidationOverview("", "", (), True)
    if not context or not routes:
        raise ConsolidationOutputError(
            "Useful Historical context requires source routes."
        )
    normalized = markdown.rstrip() + "\n"
    rendered = consolidation_envelope(key, normalized)
    if len(rendered.encode("utf-8")) > MAX_CONSOLIDATION_RENDERED_BYTES:
        raise ConsolidationOutputError(
            "Consolidation whole envelope exceeds 10,000 UTF-8 bytes."
        )
    return ValidatedConsolidationOverview(normalized, rendered, tuple(routes), False)
