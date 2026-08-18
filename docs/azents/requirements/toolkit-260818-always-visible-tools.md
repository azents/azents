---
title: "Always-Visible Toolkit Tools Requirements"
created: 2026-08-18
updated: 2026-08-18
implemented: 2026-08-18
tags: [toolkit, tool-search, engine]
document_role: primary
document_type: requirements
snapshot_id: toolkit-260818
---

# Always-Visible Toolkit Tools Requirements

- Snapshot: `toolkit-260818`
- Document reference: `toolkit-260818/REQ`

## Problem

Workspace managers cannot keep the tools of an essential attached Toolkit directly
available when an Agent uses Tool Search. Those tools remain discoverable only after a
search unless they are a platform-defined exception.

## Primary Actor

A Workspace manager configuring a Toolkit used by one or more Agents.

## Primary Scenario

The manager marks a Toolkit for direct availability. On later Agent runs with Tool
Search enabled, every currently available tool from that attached Toolkit is visible
without a preceding search.

## Supporting Scenarios

- A manager leaves the option unchanged and receives the existing Tool Search behavior.
- A manager turns the option off and later runs return to the existing deferred behavior.

## Goals

- Provide one Toolkit-level choice for direct availability of all its tools.
- Preserve existing behavior by default.
- Apply the choice consistently to current and future tools resolved from the Toolkit.

## Non-Goals

- Selecting exposure independently for individual tools within one Toolkit.
- Changing Toolkit attachment, enablement, credentials, discovery, or Tool Search ranking.
- Bypassing provider tool-declaration compatibility limits.

## Requirements

### REQ-1. Toolkit-level direct availability

A Workspace manager can choose whether all tools from a Toolkit are directly available
to Agents that use it.

**Acceptance criteria**

- The choice is available when creating and editing a Toolkit.
- When enabled, every available tool from the attached Toolkit is visible without Tool
  Search.
- The choice applies to all Agents attached to the same Toolkit.

### REQ-2. Existing behavior by default

Toolkits continue to use the existing Tool Search behavior unless a manager enables
direct availability.

**Acceptance criteria**

- New Toolkits default to the existing Tool Search behavior.
- Existing Toolkits retain the existing Tool Search behavior after migration.
- Turning direct availability off restores the existing Tool Search behavior.

### REQ-3. Preserve global Tool Search semantics

The Toolkit-level choice does not alter the Agent-level Tool Search setting or provider
compatibility constraints.

**Acceptance criteria**

- Agents with Tool Search disabled continue to receive the complete executable catalog.
- Directly available Toolkit tools count under the existing pinned declaration budget.
- Toolkit attachment, enablement, and availability checks remain unchanged.

## Fixed Constraints

- Toolkit management remains restricted by the existing Toolkit write permission.
- The setting contains no credentials or user-specific state.

## Open Assumptions

- Managers will reserve direct availability for Toolkits whose tools are important
enough to consume model-visible declaration capacity on every call.

## Confirmation

Confirmed by the requester on 2026-08-18 before ADR and design decisions began.
