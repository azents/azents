---
title: "Runtime-Aligned Model Metadata Decisions"
created: 2026-10-01
updated: 2026-10-01
tags: [model-catalog, backend, engine, scheduler, architecture, migration]
document_role: primary
document_type: adr
snapshot_id: catalog-261001
---

# Runtime-Aligned Model Metadata Decisions

- Snapshot: `catalog-261001`
- Document reference: `catalog-261001/ADR`
- Requirements: [catalog-261001/REQ](../requirements/catalog-261001-runtime-aligned-model-metadata.md)
- Decision mode: Collaborative
- Decision owner: Requester

## Context

The confirmed Requirements replace the remaining LiteLLM metadata authority after model execution moved to official provider SDKs and Pydantic AI model adapters. The current catalog lifecycle is already Azents-owned: a six-hour scheduled task and system-admin operations collect a remote source, store a validated source snapshot, publish system projections, preserve the last successful projection on failure, and keep normal reads local. Integration catalogs additionally combine provider-visible models with stored metadata under configuration-generation fencing, throttling, retry, and stale-refresh policy.

The same source snapshot is also captured locally for context fallback and estimated-cost provenance. Existing saved Agent and Workspace selections retain copied semantic model capabilities rather than following mutable catalog rows.

The remaining mismatch is authority: catalog capabilities and pricing still consume a LiteLLM-shaped payload even though LiteLLM no longer constructs or executes models. Active code, database schema, configuration, diagnostics, tests, and persisted source metadata also retain LiteLLM vocabulary.

This ADR supersedes the LiteLLM projection-source and source-snapshot decisions in `catalog-260620/ADR-D8`, `catalog-260620/ADR-D9`, `catalog-260620/ADR-D11`, `catalog-260620/ADR-D14`, and `catalog-260620/ADR-D15` only where they select LiteLLM as the active execution-target metadata authority. Their system/integration catalog ownership, stored-read, provider-availability, snapshot, failure-retention, and synchronization decisions remain authoritative unless this snapshot explicitly replaces them.

## Fixed or Derived Outcomes

- models.dev remains outside the active catalog source path.
- The Pydantic AI ecosystem's maintained metadata supplies model inventory, context, lifecycle, and pricing evidence for supported providers.
- Execution-facing capability claims follow the compatibility authority used by actual runtime model construction, including provider profiles, Azents profile overrides, protocol selection, and native OpenAI adapter policy.
- Azents retains scheduler, administrator operation, durable attempt, source snapshot, projection snapshot, publication, failure, recovery, and stored-read ownership.
- The imported library's process-global price updater is not source authority.
- Provider APIs remain the availability authority for integration-scoped catalogs.
- Missing optional metadata or pricing remains nullable and does not hide a provider-visible model or fail execution.
- Existing saved model-selection snapshots are not rewritten by catalog refresh.
- Historical documents and executed migration records remain factual; active LiteLLM identities and fallback behavior are removed.
- The explicitly validated remote source remains authoritative. A package-bundled dataset does not replace a failed remote collection or silently become a second source authority.

## Material Decision Map

- [x] `catalog-261001/ADR-D1` — use one runtime model-profile resolver as execution-capability authority
- [x] `catalog-261001/ADR-D2` — keep source synchronization and durable snapshot lifecycle under Azents ownership
- [x] `catalog-261001/ADR-D3` — persisted Pydantic metadata contract and operation-local pricing evaluation
- [x] `catalog-261001/ADR-D4` — database and deployment cutover topology for eliminating active LiteLLM state

## Decisions

### catalog-261001/ADR-D1. Use one runtime model-profile resolver as execution-capability authority

**Authority:** `catalog-261001/REQ-1`, `REQ-3`, `REQ-4`, and the requester's confirmed target-aligned capability principle.

Catalog projection and runtime model construction use one shared, credential-free model-profile resolver for a semantic provider and exact provider model identifier. The resolver composes the provider/model profile supplied by the deployed runtime library, Azents-owned provider and protocol overrides, the effective model class's supported native-tool intersection, and the native OpenAI Responses policy for providers that do not execute through `ProviderModelFactory`.

The resolved runtime profile is converted into Azents `ModelCapabilities` through one normalization boundary. Catalog code does not maintain a second list of tool, structured-output, reasoning, native-tool, or wire-compatibility support. Runtime model construction consumes the same resolver output when it creates the provider model or native adapter.

General metadata can fill model identity, display, lifecycle, context, and pricing facts, but it cannot enable an execution-facing capability denied or unknown to the runtime resolver. Provider-listing metadata can retain authority for account-visible facts explicitly documented by that provider path. When optional evidence remains unknown, the projection keeps the model's existing conservative visibility policy and leaves the individual capability disabled.

The resolver returns normalized, serializable capability evidence and a stable revision fingerprint. It does not persist raw `ModelProfile` objects because profiles contain code objects, classes, and tool types whose serialization would create a second executable authority.

**Consequences**

- Catalog capability changes follow the same dependency and Azents code revisions that change execution behavior.
- A metadata refresh can introduce a model without fabricating unsupported execution features.
- OpenAI-native and Pydantic-routed providers share the same catalog authority abstraction without pretending they use an identical transport.
- Runtime construction and catalog projection require contract tests proving equal resolution for representative provider/model families.

**Rejected alternatives**

- Use genai-prices alone for capabilities: it supplies pricing and context metadata, not the complete request and wire-compatibility contract.
- Add models.dev as a capability source: its broad flags do not define Pydantic or native OpenAI execution semantics and would introduce a second independently changing authority.
- Copy Pydantic profile rules into catalog code: duplicated model-family logic would drift from the runtime path that it is intended to describe.

**Required evidence**

- Provider-family tests compare catalog-normalized capabilities with the profile consumed by runtime construction.
- Unknown or unsupported profile fields cannot become enabled catalog capabilities.
- Repository search finds no independent duplicate of provider/model execution-capability rules in catalog projection.

### catalog-261001/ADR-D2. Keep source synchronization and durable snapshot lifecycle under Azents ownership

**Authority:** `catalog-261001/REQ-2` through `REQ-5`, `REQ-8`, and the existing stored model-catalog lifecycle retained by the Requirements.

Azents invokes the Pydantic ecosystem metadata fetch as one bounded source-collection operation from its registered system catalog task and administrator operation. It records a source-only attempt, validates and fingerprints the result, applies supersession and material-reduction guards, and publishes a durable source snapshot only after validation succeeds.

Normal catalog reads, integration syncs, context fallback, pricing capture, and model dispatch use the latest successful stored source snapshot. They never depend on process-global mutable metadata, a package import side effect, or a request-time source fetch. A failed collection records safe diagnostics and retains the prior source and projection authorities.

The scheduled task continues to own periodic refresh and the Admin API continues to own explicit system refresh. Integration sync reads the current source snapshot but never refreshes it. Source provenance identifies the remote source, content hash, adapter schema, metadata package version, and collection time without recording model content in logs.

**Consequences**

- Metadata can update independently of application deployment while reads remain deterministic and local.
- Multiple application processes observe one database authority instead of separate in-memory updater state.
- Source collection remains operable and diagnosable through existing scheduler and Admin boundaries.
- Package-bundled metadata can support deterministic tests but is not a production fallback authority.

**Rejected alternatives**

- Start `genai-prices.UpdatePrices` as a background singleton in each process: it updates only process-global memory, creates divergent authorities, and bypasses Azents attempts and durable snapshots.
- Let catalog or runtime reads fetch current metadata: external latency and failure would re-enter normal product paths.
- Fall back to package-bundled metadata after remote failure: it would replace explicit last-success authority with an independently versioned source.

**Required evidence**

- Scheduler and Admin tests prove collection and publication use the same service boundary.
- Failure, supersession, malformed payload, and material-reduction tests preserve the prior authoritative source and projections.
- Read-path and runtime tests fail if they attempt network metadata access.

### catalog-261001/ADR-D3. Persisted Pydantic metadata contract and operation-local pricing evaluation

**Authority:** requester selection on 2026-10-01, `catalog-261001/REQ-2`,
`REQ-3`, `REQ-5`, `REQ-7`, `REQ-8`, and ADR-D2.

Azents persists a replayable, versioned model metadata source contract derived
from the typed result of the public `genai-prices` fetch operation. The source
adapter converts provider identity, exact model identity, model-match logic,
context window, lifecycle state, conditional and tiered price rules, and supported
billing units into a JSON-safe Azents schema. The durable source snapshot records
the adapter schema version, source URL, content hash, `genai-prices` package
version, collection time, and normalized model count.

The persisted contract is generic model metadata state rather than a serialized
Python `DataSnapshot` or raw `ModelProfile`. Its table, repository, and domain
names use `model_metadata_source` terminology, while the row provenance identifies
`genai_prices` as the active source kind. Provider identifiers are mapped through
one explicit adapter; source-native identifiers such as `aws` and `x-ai` are not
treated as Azents provider enums or execution prefixes.

An operation captures one source snapshot and builds an isolated pricing view from
that snapshot. Provider/model lookup and price evaluation reproduce the persisted
genai-prices match and pricing semantics without installing the snapshot into
process-global library state. Context fallback reads the same captured model
record. The operation records source snapshot ID, content hash, matched source
identity, source schema version, and estimator version in applicable provenance.

Unsupported future source fields or billing rules fail validation or produce an
explicitly unavailable estimate according to their boundary. They do not silently
fall back to an older field interpretation, fabricate zero cost, hide a model, or
fail generation. Updating the adapter for a new source schema is an explicit code
and test change.

**Consequences**

- Independent background collection retains the matching and pricing behavior
  that makes genai-prices useful instead of flattening it into a lossy token-rate
  table.
- Pricing remains operation-local, immutable, and reproducible after process
  restart without using the package's global snapshot.
- The adapter is a maintained compatibility boundary with its own schema and
  dependency-version fixtures.
- The source table remains reusable for a future metadata producer without
  retaining Pydantic or LiteLLM in the database object name.

**Rejected alternatives**

- Persist only basic token prices and keep the current LiteLLM-shaped estimator:
  this loses conditional dates, off-peak windows, tiered prices, new billing
  units, and provider match behavior.
- Persist the remote JSON and invoke private genai-prices parsing APIs: repository
  conventions prohibit replacing a missing public contract with private library
  APIs.
- Serialize Python `DataSnapshot` or `ModelProfile` instances: those objects are
  not a stable JSON contract and profiles contain executable types.
- Use the process-global genai-prices snapshot for runtime estimates: it would
  break captured-snapshot provenance and permit cross-process drift.

**Required evidence**

- Golden fixtures round-trip every persisted match, conditional-date,
  time-of-day, tiered-price, and supported-unit form consumed by Azents.
- A persisted snapshot produces the same provider/model match and supported cost
  result as the typed source object for the verification matrix.
- Concurrent operations can evaluate different captured source snapshots without
  shared mutable state.
- Unknown provider, model, price unit, malformed rule, and unsupported usage
  produce explicit unavailable outcomes.

### catalog-261001/ADR-D4. Database and deployment cutover topology for eliminating active LiteLLM state

**Authority:** requester selection on 2026-10-01, `catalog-261001/REQ-3`,
`REQ-4`, `REQ-7`, `REQ-8`, ADR-D1 through ADR-D3, and the existing
last-success catalog availability policy.

The transition uses a staged shadow, atomic cutover, and cleanup sequence.

The foundation stage introduces generic model metadata source persistence, the
genai-prices source adapter, runtime profile resolver, replacement source sync,
and replacement projection path without changing current catalog pointers or
runtime metadata capture. It collects and validates the new source and can build
candidate replacement projections while existing successful catalog snapshots
remain readable.

The cutover stage requires a current validated replacement source and a verified
replacement projection for every system catalog. It switches source readers,
runtime context and pricing capture, and each prepared catalog current pointer to
the replacement authority through explicit transactional publication. Existing
integration catalog entries remain visibility evidence during transition and are
reprojected from their exact stored provider/model identities before or during
cutover; ordinary provider sync subsequently refreshes account visibility under
its unchanged lifecycle.

The cleanup stage runs only after database and repository absence checks prove
that no current catalog snapshot, active source row, served source metadata,
runtime reader, scheduler path, environment configuration, diagnostic, or
fixture depends on LiteLLM vocabulary or payload semantics. It then removes the
old source table, constraints, fields, code, configuration, tests, and temporary
shadow controls. No dual read, dual write, legacy alias, or fallback remains
after this boundary.

Before cutover, rollback is an ordinary application rollback because current
catalog and runtime authority have not changed. After cutover but before cleanup,
rollback selects the previously retained current catalog projections and source
reader only through an explicit coordinated rollback operation; normal runtime
does not automatically fall back. After destructive cleanup, rollback requires
the matching pre-cleanup database backup and application release. The deployment
runbook records these boundaries.

**Consequences**

- Model picker and normal runtime reads retain the last successful catalog while
  replacement collection and projection are prepared.
- Remote-source failure cannot force a destructive migration or empty current
  catalog.
- Temporary coexistence is bounded by explicit readiness and absence gates rather
  than becoming a permanent compatibility mode.
- Integration catalogs can preserve current provider visibility without requiring
  every customer credential to succeed during the system-source cutover window.
- Final cleanup delivers the requested zero active LiteLLM identity instead of
  renaming old payloads as new authority.

**Rejected alternatives**

- One-release destructive cutover: source or projection failure could leave empty
  system catalogs and remove operation-local context and pricing authority before
  the replacement is ready.
- Relabel the existing LiteLLM payload and rows as generic metadata: this would
  preserve false provenance and incompatible source semantics.
- Permanent dual-source reads or fallback: this would retain two authorities and
  violate complete active LiteLLM removal.
- Re-list every integration synchronously at cutover: customer credentials,
  permissions, provider availability, and quota would become global deployment
  blockers.

**Required evidence**

- Foundation validation proves the replacement source and candidate system
  projections can be built without changing current pointers.
- Cutover tests prove each catalog pointer switches atomically and a failed
  publication leaves the prior pointer unchanged.
- Seeded migration tests cover existing source rows, system and integration
  projections, optional xAI enrichment, pricing provenance, and catalog entries
  containing legacy source metadata.
- Cleanup checks prove active schema, rows, code, configuration, API fixtures,
  diagnostics, and telemetry contain no LiteLLM source identity.
- The deployment runbook distinguishes pre-cutover, post-cutover/pre-cleanup, and
  post-cleanup rollback procedures.
