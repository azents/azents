---
title: "Always-Visible Toolkit Tools"
created: 2026-08-18
tags: [toolkit, tool-search, engine, architecture]
document_role: primary
document_type: adr
snapshot_id: toolkit-260818
---

# Always-Visible Toolkit Tools

- Snapshot: `toolkit-260818`
- Document reference: `toolkit-260818/ADR`
- Requirements: [`toolkit-260818/REQ`](../requirements/toolkit-260818-always-visible-tools.md)

## Decision Map

- **Fixed:** The choice is Toolkit-wide, defaults to existing Tool Search behavior, and
does not bypass Agent-level Tool Search disablement or provider declaration limits.
- **Accepted material decision:** Persist the choice as common ToolkitConfig policy and
carry it into catalog exposure classification.
- **Agent-owned details:** Field naming, form placement, helper boundaries, and fixture
composition.

## toolkit-260818/ADR-D1. ToolkitConfig owns the direct-exposure policy

The direct-exposure choice is persisted as a common ToolkitConfig property rather than
inside provider-specific configuration JSON or on each Agent attachment.

This makes one manager-controlled value authoritative for every Agent attached to the
Toolkit, keeps provider configuration focused on integration behavior, and allows a
Toolkit update revision to invalidate the active session binding normally.

The default is the existing deferred Tool Search behavior. Existing and newly created
ToolkitConfig records receive that default unless the manager explicitly enables direct
exposure.

### Rejected alternatives

- **Provider-specific config fields:** duplicates a platform-wide policy across every
  provider schema and allows inconsistent support.
- **AgentToolkit attachment setting:** permits the same Toolkit to behave differently per
  Agent, contrary to the requested ToolkitConfig-level choice.
- **Per-tool selection:** adds a separate policy lifecycle and UI outside the confirmed
  scope.

## toolkit-260818/ADR-D2. Catalog classification applies the policy to every tool

When Tool Search is enabled, the engine classifies every executable tool sourced from an
opted-in ToolkitConfig as direct. Future tools resolved from that Toolkit inherit the
same policy automatically.

Existing platform-defined direct exceptions remain direct. The existing compatibility
budget remains authoritative: opted-in tools count as pinned direct declarations and the
run fails through the established compatibility error when they cannot fit.

### Rejected alternatives

- **Automatic fallback to deferred tools on budget overflow:** would make the manager's
  direct-availability choice unreliable and introduce a new hidden fallback mode.
- **Copying tool names into persisted policy:** would become stale as MCP snapshots or
  provider toolsets change.
