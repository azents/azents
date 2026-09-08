---
title: "Composer Model Execution Options Design"
created: 2026-09-08
implemented: 2026-09-08
tags: [models, frontend, engine, api]
document_role: primary
document_type: design
snapshot_id: execution-260908
---

# Composer Model Execution Options Design

- Snapshot: `execution-260908`
- Requirements: [execution-260908/REQ](../requirements/execution-260908-model-execution-options.md)
- Decisions: [execution-260908/ADR](../adr/execution-260908-model-execution-options.md)

## Current Behavior and Gap

`ModelCapabilities` describes static abilities. Agent selections snapshot that contract and source metadata. The composer already controls target label and reasoning effort using requested and Session-applied inference profiles. Mailbox and Run rows retain requested intent; prepared Session inference state freezes physical model and settings. OpenAI Responses request lowering already supports `service_tier` and uses the official SDK for API-key and ChatGPT OAuth HTTP/WebSocket requests. None of these surfaces currently exposes switchable execution options.

## Architecture and Ownership

```mermaid
flowchart LR
  R[Code-owned option registry] --> P[Provider support projection]
  P --> C[Stored catalog support IDs]
  C --> A[Agent model selection snapshot]
  A --> U[Composer option controls]
  U --> I[Requested and Session-applied intent]
  I --> Q[Mailbox and original Run intent]
  Q --> S[Prepared inference snapshot]
  S --> L[Bounded provider translation]
  L --> H[Official SDK HTTP or WebSocket]
```

Definitions, model support, and user intent are independent axes. The first option is a boolean Fast execution preference. A registry owns recognized IDs and provider translation contracts. Model support is a top-level `supported_execution_options` list, never a `ModelCapabilities` field or built-in tool. Per-profile `enabled_execution_options` is validated against the saved selected model's support. No arbitrary request parameters enter from clients.

## Catalog and Public Contracts

Add a separate JSONB supported-ID column to catalog entries and carry it through repository DTOs, projection, public catalog output, and catalog-to-selection normalization. Add supported IDs beside normalized capabilities on `AgentModelSelection`. Every new projection explicitly supplies IDs, including all-off for unimplemented providers. Existing catalog rows start with an empty support list; historical selection JSON without the field deserializes as empty. No runtime provider listing or raw metadata inference upgrades old selections. Catalog sync followed by model reselection is the activation boundary for existing Agents.

Add enabled IDs to requested, applied, and Session-applied profile contracts. Expose the same list in Session model-profile replacement/read responses, Session projections, requested event provenance, and applied execution provenance. API/OpenAPI and generated Python/TypeScript clients are regenerated together.

## State, Persistence, and Lifecycle

- Store Session-applied, mailbox-requested, Run-requested/original, and prepared-current option lists at their existing respective persistence boundaries.
- Existing rows acquire all-off lists through the migration; serialized historical profile absence uses the same all-off interpretation. New constructors explicitly pass the list.
- Add consistency constraints so non-empty persisted intent cannot exist without its corresponding model target.
- Profile replacement and input admission retain current authorization, row locking, idempotency hashing, and mutation transaction boundaries. Hashes include the option selection.
- Draft model switching intersects enabled choices with new support. Submitted explicit intent is validated and fails deterministically if unavailable rather than silently changing the requested mode.
- Already-prepared calls and recovery/retry remain immutable. Session preference changes affect the next fresh preparation.
- Same-target parent/full-history inheritance preserves the prepared choice. Implicit inheritance onto a different target intersects supported options; explicit requested unsupported options fail.
- Auxiliary title and compaction calls explicitly use all-off options.

## Provider Translation and Failures

Fast preserves model identity, reasoning effort, tools, and authentication. Translation produces only the reviewed provider request field. Both OpenAI authentication paths use `service_tier: priority` when Fast is enabled. API Fast-off uses explicit standard routing rather than an account project's automatic default. ChatGPT Fast-off follows the verified Codex standard request semantics. Unrelated providers never receive OpenAI service-tier fields.

OpenAI model eligibility is an exact reviewed identifier list grounded in official Fast pricing; unreviewed aliases and date-snapshot variants fail closed. ChatGPT eligibility is current account-catalog `service_tiers` metadata only; absent/empty declarations mean unsupported, without legacy speed metadata fallback. Entitlement, quota, regional limitations, and provider availability remain runtime concerns. Unsupported, unknown, and malformed option intent fails before provider invocation. Provider rejection uses existing failure/retry contracts without a Fast-to-standard application fallback.

Existing cost estimation receives the actual response tier. Premium responses with unknown premium pricing must not be priced silently at the standard rate. Normalize a returned Fast alias for the installed pricing library when needed. API estimates and ChatGPT credit consumption remain different concepts; do not invent a fixed multiplier or latency guarantee.

## Composer Behavior

Render supported execution options independently beside the existing model/reasoning controls. The semantic option ID is `fast`. Public response DTOs expose `execution_option_definitions` with id, label, description, qualitative provider-specific cost hint, and `control: boolean`, projected from the backend registry. Persist only IDs, never presentation metadata or computed serialization fields in model selections. Keep known definitions available for historical provenance even when current model support disappears. Use localized labels, a cost/usage explanation, visible selected state, and keyboard-operable boolean controls. Keep read-only permissions and mobile overflow behavior. Fast starts off.

A new Session holds the selected option in composer state until its first input. An existing Session saves directly using the existing model-profile replacement flow, without a transcript message or extra Apply step. Save failures remain visible; pending state prevents duplicate writes and success is not assumed. Model switching removes unsupported draft selections. Existing image generation and built-in-tool interfaces remain unchanged.

## Security and Operations

No authentication flow, credential storage, provider URL, permission rule, or endpoint trust boundary changes. The server owns recognized options and provider mapping; the client cannot inject arbitrary SDK parameters. No credential, provider request body, or raw response is added to logs. Options add only bounded non-secret execution provenance.

Roll out database migration before new server/client code. Old snapshots remain all-off, and resync/reselection explicitly creates support-aware snapshots. Rollback requires reverting the application with the additive schema retained until its data can safely be downgraded; no live environment changes are included in this PR.

## Requirement Traceability and Feasibility

- REQ-1: independent definition/support/intent types and registry; current catalog and selection snapshot boundaries provide the implementation seam.
- REQ-2: generic composer controls and existing Session profile replacement; new-session draft state already exists.
- REQ-3: provider-specific translation through existing Responses option forwarding and HTTP/WebSocket SDK paths; static official API policy and account ChatGPT metadata supply support evidence.
- REQ-4: existing mailbox, Session, Run, requested/applied profiles and prepared inference state supply durable boundaries; all profile-copy paths require coordinated changes.

Feasibility: conditional on implementing the complete storage/copy path and verifying generated clients and the deterministic provider journal. No new transport or external service is required. The local development clone is available; paid-account entitlement and latency claims are not part of deterministic feasibility evidence.

## Test Strategy

Primary E2E verification extends Session model-profile and per-prompt inference tests using the deterministic provider fixture: support discovery, Fast on/off request tier, no-message update, reload, model switching, queued input, invalid options, idempotency, permissions, and retry/immutable preparation. The provider journal is authoritative for request assertions; avoid fixed sleeps. Add actual browser composer coverage for keyboard, saving/error state and narrow layout, plus stories for deterministic visual states.

Unit/integration coverage verifies registry rejection, exact API model/date policy, ChatGPT metadata, catalog-to-selection propagation, migration defaults/constraints, each profile copy and serialization boundary, prepared RunRequest mapping, auxiliary all-off calls, HTTP/WebSocket option forwarding, and actual-tier pricing behavior. Unsupported providers and unchanged built-in tools are regression controls.

Use testenv's deterministic prerequisite/fixture support rather than live credentials for required CI. Live OAuth/API tests require existing non-secret prerequisite references and explicit available credentials; absence is reported as not tested, not a pass. Do not add paid latency benchmarks or expose tokens. Record exact commands and results. Run backend Ruff/typecheck/pytest, frontend format/lint/typecheck/build, generated-client checks, E2E, code/spec review and single-PR CI.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Independent registry, support snapshots, and enabled profile intent | REQ-1; ADR-D1 | decided |
| M2 | Catalog and saved selection support authority with fail-closed old snapshots | REQ-1, REQ-3; ADR-D1 | decided |
| M3 | Durable applied/requested/prepared lifecycle and immutable retry | REQ-4; ADR-D2 | decided |
| M4 | Validated provider support and bounded Fast wire/cost handling | REQ-3; ADR-D3 | decided |
| M5 | Composer direct control and model-transition persistence | REQ-2; ADR-D4 | decided |
| M6 | Existing permission, SDK, failure and non-secret provenance boundaries | REQ-3, REQ-4; current conversation and ChatGPT OAuth specs | existing |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Two-field profile construction, serialization, and equality/hash assumptions | REQ-2, REQ-4; ADR-D2 | Complete profile including option IDs | REST/live, storage/copy, worker, composer | Search constructors/parsers; round-trip and idempotency tests |
| Catalog/selection DTOs that cannot express execution support | REQ-1; ADR-D1 | Explicit support list alongside static capabilities | Projection, persistence, public output, generated clients | Projection/selection round-trip tests |
| Generated schema/client surfaces | Same API authority as M1-M5 | Regenerated authoritative clients | Public/admin clients as affected | Generator checks and typecheck |

No static capabilities, built-in tools, authentication paths, or historical implemented documents are removed.

## Non-Blocking Risks

Provider metadata and entitlement may change. Old Agent snapshots need reselection to expose new options. No actual user study or latency benchmark has been performed. The initial option value kind is boolean; other value kinds require a later complete contract extension rather than accepting arbitrary JSON.

## Design Approval

- Mode: Autonomous.
- Decision owner: delegated technical interviewee.
- Approved on: 2026-09-08 KST.
- Approved Design revision: `1`.
- Approved authority IDs: `M1, M2, M3, M4, M5, M6`.
- Approved scope: independent execution-option definition/support/intent contracts, catalog and immutable prepared snapshots, bounded Fast provider semantics, immediate composer control, and preserved authorization/failure boundaries.
- Authority, feasibility, and removal/replacement audits: passed. Implementation is authorized under the requester's delegated single-PR scope. Public descriptor `control` is the literal string `"boolean"`.
