---
title: "User-Friendly Toolkit Identifiers Requirements"
created: 2026-10-01
updated: 2026-10-01
tags: [toolkit, frontend, api, engine]
document_role: primary
document_type: requirements
snapshot_id: toolkit-261001
---

# User-Friendly Toolkit Identifiers Requirements

- Snapshot: `toolkit-261001`
- Document reference: `toolkit-261001/REQ`

## Problem

Toolkit administrators currently have to provide a unique technical Slug even when they
only intend to name and configure a service connection. The visible default does not
follow the connection Name, non-Latin Names do not have an explicit fallback, and a
second configuration can force the administrator to understand model tool prefixes and
resolve a collision manually.

The product needs simple Name and Slug defaults while still supporting multiple Toolkit
configurations with the same preferred Slug and preserving unique executable tool names
inside each Agent.

## Primary Context

### Primary Actor

A Workspace Toolkit administrator or an administrator configuring a Toolkit for one
saved Agent.

### Primary Scenario

The administrator selects a Toolkit type, reviews the proposed Name and Slug, changes
only the values that need customization, and saves the configuration. A generic MCP
connection requires a meaningful Name. The administrator can later create or connect
another Toolkit with the same Slug without resolving a conflict, while the Agent still
receives distinct executable tool names.

## Supporting Scenarios or Effects

- A non-MCP Toolkit uses its canonical Toolkit name when the administrator leaves Name
  empty.
- A Name written in Korean, Japanese, or another script cannot produce the permitted
  ASCII Slug, so the product falls back to the canonical Toolkit name.
- A user-supplied Slug remains available for administrators who want a specific tool
  prefix.
- Existing Toolkit configurations keep their stored Name and Slug during rollout.

## Goals

- Make Name and Slug defaults understandable without pre-filling editable input values.
- Require a meaningful Name for generic MCP connections.
- Let administrators override the proposed Slug without requiring them to make it
  unique.
- Keep executable tool names unique when one Agent uses Toolkit configurations with the
  same stored Slug.
- Preserve existing Toolkit ownership, permissions, configuration, and stored values.

## Non-Goals

- Adding or removing Toolkit provider types.
- Making Toolkit Names unique.
- Expanding the permitted Slug character set beyond lowercase ASCII letters, numbers,
  and underscores.
- Automatically rewriting existing Toolkit Names or Slugs.
- Letting users directly choose the final disambiguated runtime namespace.
- Changing Toolkit credentials, authorization, enablement, ownership, or sharing
  semantics.

## Requirements

### REQ-1. Dependency-ordered Name and Slug fields

The Toolkit form must present Name and Slug after Toolkit type in the order needed to
understand their defaults.

**Acceptance criteria**

- The common field order begins with Toolkit type, Name, and Slug, followed by the
  existing descriptive and provider-specific settings.
- A non-MCP Name field shows the selected Toolkit's canonical name as a placeholder and
  may be left empty.
- Saving an empty non-MCP Name stores the canonical Toolkit name.
- A generic MCP Name is required and does not silently store `MCP` as its default.
- Changing Toolkit type recomputes untouched placeholders without overwriting a Name or
  Slug that the administrator entered.

### REQ-2. Optional Slug with a Name-derived default and fallback

An administrator may leave Slug empty or provide an explicit Slug.

**Acceptance criteria**

- The empty Slug field shows the Slug that would be derived from the current effective
  Name as a placeholder.
- Saving an empty Slug stores a deterministic slugification of the effective Name.
- If the effective Name cannot produce a valid Slug, saving uses a slugification of the
  canonical Toolkit name instead.
- A user-entered Slug is stored as entered after normalization and format validation.
- Only an invalid explicit Slug produces a Slug field validation error; an automatically
  derived or fallback Slug does not require user correction.

### REQ-3. Duplicate stored Slugs

Toolkit configurations may use the same stored Slug without making the administrator
resolve a uniqueness conflict.

**Acceptance criteria**

- Duplicate Slugs are allowed for Workspace-shared Toolkit configurations, Agent-owned
  Toolkit configurations, and Toolkits that become effective for the same Agent.
- Create, update, attach, and enable operations do not fail because another Toolkit has
  the same Slug.
- Duplicate Slugs remain visible as the stored administrator-selected or default base
  alias; the product does not silently rewrite them to make storage unique.

### REQ-4. Unique executable tool names per Agent

An Agent must receive an unambiguous executable tool catalog even when effective
Toolkits have duplicate stored Slugs.

**Acceptance criteria**

- Every executable tool has a unique final model-visible name within one Agent run.
- The ordinary single-Toolkit case does not receive an unnecessary stable-ID suffix.
- When duplicate base aliases would produce a final-name collision, the system applies
  a compact disambiguation without asking the administrator to change Slug.
- The model can distinguish configurations with the same Slug through their Toolkit
  Name and safe connection metadata.
- Toolkit execution, Tool Search, runtime hooks, and user-visible tool activity refer to
  the same selected Toolkit after disambiguation.

### REQ-5. Existing configuration compatibility

The rollout must preserve existing Toolkit configurations and unaffected execution
behavior.

**Acceptance criteria**

- Existing ToolkitConfig Name and Slug values are unchanged by migration.
- Existing Toolkits without an effective final-name collision keep their current
  model-visible tool names.
- Existing ownership, sharing, Agent attachment, credentials, authorization, enabled
  state, and provider settings are unchanged.
- Existing API clients that already send Name and Slug continue to be accepted when the
  values satisfy format and provider requirements.

## Fixed Constraints

- Persisted Slug remains a non-empty lowercase ASCII identifier after defaults are
  resolved.
- Final model-visible tool names remain unique within each Agent's executable catalog.
- Generic MCP Name is required for both Workspace-shared and Agent-owned creation.
- Frontend placeholders, submitted defaults, and persisted Name and Slug values must
  resolve to the same observable result across supported clients.
- Existing credentials and secret-redaction contracts remain unchanged.

## Open Assumptions

- The exact deterministic slugification algorithm is a technical design decision as long
  as it satisfies the accepted examples and Slug format.
- The persistence and lifecycle of effective runtime disambiguation are technical design
  decisions as long as tool selection remains unambiguous and existing unaffected tool
  names remain stable.
- Product copy may describe Slug as an advanced tool prefix while keeping it in the
  common dependency order.

## Confirmation

Confirmed by the requester on 2026-10-01 before ADR and design decisions began.
