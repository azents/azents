---
title: "Always-Visible Toolkit Tools Design"
created: 2026-08-18
updated: 2026-08-18
implemented: 2026-08-18
tags: [toolkit, tool-search, engine, api, frontend]
document_role: primary
document_type: design
snapshot_id: toolkit-260818
---

# Always-Visible Toolkit Tools Design

- Snapshot: `toolkit-260818`
- Document reference: `toolkit-260818/DESIGN`
- Requirements: [`toolkit-260818/REQ`](../requirements/toolkit-260818-always-visible-tools.md)
- Decisions: [`toolkit-260818/ADR`](../adr/toolkit-260818-always-visible-tools.md)

## Current Behavior and Gap

ToolkitConfig stores common management state and provider-specific configuration. Agent
execution resolves attached ToolkitConfigs into Toolkit bindings, builds one executable
catalog, and classifies DB-attached service tools as deferred except for explicit
platform control tools.

There is no ToolkitConfig-level input that changes this classification for every tool
from one integration.

## Architecture and Ownership

ToolkitConfig remains the source of truth for the policy. A non-null boolean common
property defaults to false. Repository, service, and Public API models expose the same
value, and Toolkit create/edit UI submits it under the existing Toolkit write permission.

Runtime resolution copies the persisted value into the immutable Toolkit binding for the
run. Catalog source metadata then carries the value to the common exposure classifier.
The classifier returns direct exposure before applying registered per-tool exceptions
when the source policy is enabled.

Provider-specific Toolkit config models, AgentToolkit attachments, and Tool Search
working-set state do not own or duplicate the policy.

## Data and Migration

- Add a non-null boolean to `toolkit_configs` with a database default of false.
- Existing records therefore retain deferred classification after migration.
- Create requests default to false; update requests modify the field only when present.
- Any persisted update increments the existing ToolkitConfig revision, so session
  Toolkit lifecycle reconciliation replaces a stale binding normally.

Downgrade removes only the new column. No Tool Search working-set migration is required:
direct tools are ignored by deferred projection while enabled and existing names may
remain harmlessly in recency state.

## API and UI

Public ToolkitConfig create, response, and partial-update contracts expose the boolean.
Generated Public API clients are regenerated from OpenAPI.

The shared Toolkit form includes one switch for all registered provider types. Create
mode starts off. Edit mode uses the persisted value. The explanatory copy states that
all tools remain visible without Tool Search.

## Runtime Behavior

When Agent Tool Search is enabled:

1. attached and enabled ToolkitConfigs resolve as before;
2. the binding captures the ToolkitConfig policy;
3. each executable catalog entry retains that source policy;
4. all entries from an enabled policy are classified direct;
5. direct entries are included in every prepared model call and are excluded from the
   deferred search index.

When Agent Tool Search is disabled, the existing complete-catalog path remains unchanged.
Provider compatibility budgeting treats these tools as pinned direct declarations.

## Security and Permissions

The field uses existing Toolkit create/update authorization. It contains no secret and
does not expand Toolkit attachment, credential, scope, or provider permissions. It only
changes model-visible declaration membership for already executable tools.

## Failure, Rollback, and Recovery

- Provider declaration budget overflow follows the existing deterministic pre-provider
  failure path.
- Invalid or unavailable Toolkit tools remain absent regardless of this policy.
- Rolling application code back after schema migration is safe because the added column
  has a database default and older code ignores it.
- Database downgrade discards manager selections and restored code resumes deferred
  behavior.

## Test Strategy

Primary product verification covers create/edit persistence and an Agent run with Tool
Search enabled, confirming that an opted-in Toolkit tool is declared without search and
that a default Toolkit tool remains deferred.

Repository and API tests verify false defaults and update round trips. Engine unit tests
verify source classification and catalog projection. Frontend type checking and form
tests verify request/response wiring. Existing Tool Search and compatibility-budget
suites cover unchanged ranking, activation, and overflow behavior.

No new live credential fixture is required. A deterministic fake registered Toolkit is
sufficient for runtime coverage. CI should fail rather than skip the unit and contract
coverage; live provider E2E remains optional because the policy is provider-independent.

## Feasibility

- **REQ-1: feasible.** ToolkitConfig already flows through repository, API, runtime
  resolution, and shared UI form boundaries.
- **REQ-2: feasible.** A non-null false database/API default preserves existing records
  and create behavior.
- **REQ-3: feasible.** Exposure classification and provider budget projection already
  distinguish direct and deferred entries centrally.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | ToolkitConfig is the shared persisted policy owner. | `toolkit-260818/REQ-1`, `toolkit-260818/ADR-D1` | `decided` |
| M2 | False is the migration and create default. | `toolkit-260818/REQ-2`, `toolkit-260818/ADR-D1` | `required` |
| M3 | The catalog classifies every tool from an opted-in ToolkitConfig as direct. | `toolkit-260818/REQ-1`, `toolkit-260818/ADR-D2` | `decided` |
| M4 | Existing Agent Tool Search and declaration-budget behavior remains authoritative. | `toolkit-260818/REQ-3`, Toolkit Living Spec | `existing` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Unconditional deferred-by-default classification for every non-exception DB Toolkit tool | `toolkit-260818/REQ-1`, `toolkit-260818/ADR-D2` | Conditional direct classification from ToolkitConfig policy; deferred remains the default | Common catalog exposure classifier | Tests cover both policy values and no provider-specific classifier is added |
| No ToolkitConfig exposure control in API/UI | `toolkit-260818/REQ-1` | Common create/response/update field and shared form switch | Public Toolkit contracts and Toolkit form | Generated clients and form submission include the field |

## Design Approval

- Mode: `Collaborative`
- Decision owner: `Requester`
- Approved on: `2026-08-18`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4`
- Approved scope: `Implement the requested ToolkitConfig option with deferred behavior as the default and direct catalog exposure when enabled.`
