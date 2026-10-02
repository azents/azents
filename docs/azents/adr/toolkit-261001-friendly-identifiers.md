---
title: "User-Friendly Toolkit Identifiers"
created: 2026-10-01
tags: [toolkit, frontend, api, engine, architecture]
document_role: primary
document_type: adr
snapshot_id: toolkit-261001
---

# User-Friendly Toolkit Identifiers

- Snapshot: `toolkit-261001`
- Document reference: `toolkit-261001/ADR`
- Requirements: [`toolkit-261001/REQ`](../requirements/toolkit-261001-friendly-identifiers.md)

## Decision Map

### Fixed or derived outcomes

- Persisted ToolkitConfig Slug is a non-unique base alias (`toolkit-261001/REQ-3`).
- Final model-visible tool names remain unique within one Agent catalog
  (`toolkit-261001/REQ-4`).
- Existing ToolkitConfig Name and Slug values are not rewritten
  (`toolkit-261001/REQ-5`).
- Generic MCP Name is required, while non-MCP Name and every Slug may use the
  confirmed defaults (`toolkit-261001/REQ-1`, `REQ-2`).
- Toolkit execution, Tool Search, runtime hooks, and tool activity must share one
  effective namespace decision (`toolkit-261001/REQ-4`).

### Material technical decisions

- **D1 — Accepted:** backend materialization authority with frontend local preview.
- **D2 — Accepted:** one durable PostgreSQL Agent+Toolkit namespace relation.
- **D3 — Accepted:** monotonic ordinal allocation with durable reservation.
- **D4 — Accepted:** two-stage Foundation then Capability compatibility rollout.

### Agent-owned implementation details

- Exact module, class, table, and helper names.
- Exact deterministic slugification implementation that satisfies the Requirements.
- Equivalent local transaction and fixture composition after the material persistence
  and lifecycle decisions are accepted.

## toolkit-261001/ADR-D1. Backend materializes defaults; frontend previews them locally

The backend is the canonical authority that resolves and persists omitted Name and Slug
values. The Web form independently computes the same values only for immediate
placeholders. An untouched placeholder is omitted from the request rather than copied
into the payload. A user-entered Name or Slug is sent explicitly.

The backend resolves a non-MCP empty Name to the registered Toolkit Provider name,
requires an explicit generic MCP Name, derives an omitted Slug from the effective Name,
and applies the canonical Toolkit name fallback required by `toolkit-261001/REQ-2`.
The create response's persisted Name and Slug are authoritative for subsequent UI state.

Python and TypeScript implementations use one versioned set of language-neutral
conformance vectors covering canonical defaults, ASCII normalization, separators,
length boundaries, non-Latin fallback, and explicit-value preservation. CI must reject
any frontend/backend difference. This accepts duplicated pure preview logic while
preventing it from becoming a second persistence authority.

### Rejected alternatives

- **Frontend materialization with backend validation only:** direct Public API clients
  would need to reproduce product defaults, and omitted values could behave differently
  by client.
- **Backend preview endpoint for every Type or Name change:** it provides one computation
  implementation but makes responsive placeholders depend on network latency, debounce,
  and a new failure state. The confirmed behavior is small and deterministic enough for
  local preview with conformance tests.
- **Copying placeholder values into every request:** this turns preview state into an
  implicit client authority and can persist a drifted value before CI or monitoring
  detects the mismatch.

## toolkit-261001/ADR-D2. One durable Agent+Toolkit relation owns effective namespaces

Use one PostgreSQL-backed relation keyed by Agent and ToolkitConfig as the canonical
authority for the effective namespace applied to that Toolkit inside the Agent's tool
catalog. The relation covers both Workspace-shared attachments and directly Agent-owned
ToolkitConfigs; ownership kind does not create a second namespace source.

Runtime resolution reads the effective Toolkit relation together with this namespace
projection. The Engine binding and catalog source carry both the stored base Slug and the
effective namespace. Final tool declarations and executor routing use the effective
namespace, while product/API projections continue to expose the stored Slug. Tool Search,
runtime hooks, durable tool-call source snapshots, and activity projection use the same
catalog-selected source rather than re-parsing or independently deriving Toolkit identity.

Namespace allocation and Toolkit relation mutations share Agent-scoped transactional
serialization. A run/read path must not invent a missing namespace or silently choose a
different value; after rollout, a missing allocation for an effective persisted Toolkit
is an invariant failure.

### Rejected alternatives

- **Stateless derivation on every run:** topology or ordering changes can rename existing
  tools, while stable hash suffixes spend tokens and expose implementation identity on
  every collision.
- **Split storage on AgentToolkit and ToolkitConfig:** shared and Agent-owned Toolkits
  would have different namespace authorities even though runtime consumes one effective
  relation.
- **Session Toolkit State:** different Sessions of the same Agent could receive different
  names, and management transactions could not reserve namespaces before execution.

## toolkit-261001/ADR-D3. Allocate monotonic ordinals and retain reservations

Each Agent and stored base Slug has a durable monotonic allocation sequence. The first
allocation uses the base Slug without a suffix; later allocations use `_2`, `_3`, and so
on. An Agent+Toolkit namespace allocation is created when an Agent-owned ToolkitConfig
is created or a Workspace-shared Toolkit is attached, including disabled Toolkits, so
later enablement does not rename tools.

Disablement and shared detachment do not delete the Agent+Toolkit allocation. Re-enabling
or reattaching the same Toolkit restores the same namespace. Toolkit deletion removes
the active Agent+Toolkit mapping, but the Agent+base-Slug sequence remains so a later,
unrelated Toolkit does not reuse an identity that may still exist in Session context or
Tool Search working-set state. Agent deletion removes both mappings and sequences.

An explicit stored Slug change is an intentional tool-identity change. Every currently
effective affected Agent receives a new allocation from the new base Slug in the same
Agent-serialized mutation. Detached historical mappings are refreshed when that Toolkit
is attached again. Existing prepared Run catalogs remain immutable; the next Toolkit
reconciliation uses the new namespace. The old ordinal remains retired.

### Rejected alternatives

- **Delete allocation on disable or detach and reuse the lowest free suffix:** reattach
  can rename the same Toolkit and an old final name can later route to another Toolkit.
- **Reuse namespaces after Toolkit deletion:** Session text and working-set entries can
  outlive the Toolkit row, so reuse can silently change their referent.
- **Use a Toolkit ID hash for every collision:** this avoids sequence state but produces
  longer opaque names and spends more model tokens than compact ordinals.

## toolkit-261001/ADR-D4. Roll out duplicate-safe readers before duplicate writes

Ship the change through two compatibility releases.

The **Foundation release** adds the namespace allocation and sequence schema, backfills
all current effective Agent+Toolkit relations with the existing Slug as their effective
namespace, and moves runtime resolution, Tool Search, hooks, events, and management
transactions to the new authority. Its readers tolerate duplicate stored Slugs, but its
writers continue to reject duplicates through explicit transactional checks while the
current unique indexes remain. The complete API and Worker fleet must run this release
or later before the next stage.

The **Capability release** removes the persisted Slug unique indexes and local/effective
conflict rejection, relaxes Name and Slug create inputs, enables the new placeholder UI,
and permits duplicate Slug writes. Because every deployed reader is already
namespace-aware, rolling deployment cannot expose duplicate Slugs to a legacy catalog
builder.

After duplicate rows exist, rollback may return only to Foundation-compatible,
duplicate-aware code. Schema downgrade or rollback to pre-Foundation readers is
prohibited. A Capability rollback keeps the forward schema and allocations, rejects new
duplicate writes transactionally, and continues reading existing duplicates safely.

### Rejected alternatives

- **One maintenance cutover:** it avoids mixed versions but introduces product downtime
  and a larger all-or-nothing recovery event for a change that can be made reader-first.
- **One rolling release with lazy allocation:** a legacy Worker can observe duplicate
  Slugs, and run preparation would gain a write/retry path before publishing a catalog.
- **Dropping unique indexes in Foundation:** it would permit out-of-band or racing
  duplicate writes before every reader is proven namespace-aware.
