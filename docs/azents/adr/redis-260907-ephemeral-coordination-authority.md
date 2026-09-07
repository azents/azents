---
title: "Ephemeral Redis Coordination Authority"
created: 2026-09-07
tags: [architecture, backend, reliability, redis]
document_role: primary
document_type: adr
snapshot_id: redis-260907
---

# Ephemeral Redis Coordination Authority

- Snapshot: `redis-260907`
- Document reference: `redis-260907/ADR`
- Requirements: [Ephemeral Redis Coordination Authority Requirements](../requirements/redis-260907-ephemeral-coordination-authority.md) (`redis-260907/REQ`)

## Context

The confirmed `redis-260907/REQ` requires every Redis-backed capability to resume safely after Redis/Valkey is restored completely empty, without restoring keys, streams, locks, cursors, counters, indexes, or live projections. Lost in-flight work fails closed, durable state remains authoritative, and Provider enrollment rate limiting is explicitly best-effort across Redis loss.

Runtime Control currently allocates Provider and Runner connection generations through a subject-scoped Redis `INCR` and makes that counter non-expiring with `PERSIST`. Runtime Provider and Runner do not choose this value; each receives the accepted generation from Control and returns it in later messages. PostgreSQL Provider connection history has a unique `(provider_id, generation)` identity, while Runtime state projections accept only non-regressing Provider and Runner generations. Empty Redis can therefore reuse or regress a value that durable state and old streams already observed.

The same Redis namespace also holds current connection records, request/reply/body streams, operation metadata, and bounded system metrics. Those records are valid volatile coordination. Worker broker signals and leases, Runtime Transfer state, interactive Terminal state, live projections, External Channel conversation locks, and enrollment rate limits already have distinct failure and recovery boundaries; this snapshot must preserve them without creating a second durable authority.

Reference local deployment currently mounts a persistent Valkey data volume, while testenv Valkey does not. Current Runtime Control Living Spec simultaneously calls coordination volatile and requires generation counters to persist in Redis.

## Decision Map

### Fixed or derived outcomes

- Runtime Control continues issuing accepted Provider and Runner connection authority; clients never choose it.
- Connection authority remains a positive monotonic numeric generation in the current protocol shape.
- Redis retains current connection routing and bounded operation transport as volatile state.
- Redis outage may interrupt service; recovery after an empty replacement is automatic.
- Lost operations, transfers, Terminals, signals, leases, locks, and live projections fail closed and are not reconstructed as success.
- PostgreSQL and existing object-storage responsibilities remain the durable recovery authorities.
- Provider enrollment rate limiting remains best-effort and may start a fresh window after Redis reset.
- Reference Valkey deployment and operator documentation must not require persistence, replication, or HA.
- Implemented historical Requirements, ADRs, and Designs remain unchanged.
- No permanent compatibility reader, dual authority, or fallback retains Redis generation persistence after migration.
- A database transaction never contains a Redis, HTTP, gRPC, filesystem, object-storage, or other external call. Every external effect occurs only after the preceding database transaction has committed or rolled back.

### Pending material decisions

- [x] `redis-260907/ADR-D1` — Use one durable per-subject connection-generation high-water relation.
- [x] `redis-260907/ADR-D2` — Use one-shot volatile candidates with DB-only allocation, preflight, and acceptance transactions.
- [x] `redis-260907/ADR-D3` — Seed migration-time Home subjects into a safe numeric band and use a strict namespace cutover.
- [x] `redis-260907/ADR-D4` — Represent JSON-exposed connection generations as canonical decimal strings.

### Agent-owned implementation details

Exact schema object names, repository and service module boundaries, helper types, Lua function layout, bounded timeout and retry constants, structured log event names, fixture names, and test file organization remain implementation-owned when they do not add another authority, mode, compatibility path, or recovery behavior.

## Decisions

### redis-260907/ADR-D1: Use one durable per-subject connection-generation high-water relation

**Affected requirements:** `redis-260907/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-7`, `REQ-8`

PostgreSQL owns one connection-generation high-water row for each Runtime Control connection subject. The subject identity is the closed connection kind, Provider or Runner, plus its existing Provider or Runtime identifier. Runtime Control allocates the next positive monotonic generation from this relation before returning accepted connection authority. Redis and in-memory coordination receive the allocated generation and do not allocate, persist, restore, or infer it.

The high-water row is independent from current connection records and observed Runtime state. It remains after the current Redis registration expires, after Provider connection-history rows become disconnected, and across logical Runtime stop, removal, or re-add boundaries where the subject identity remains valid. This prevents a later connection from reusing authority previously issued for the same subject.

The relation deliberately has no polymorphic foreign key to both Provider and Runtime tables. Subject existence and registration authorization remain validated through their current domain services before generation allocation. Counter retention prevents identity reuse from recreating an old fencing value and is not product history or current connection state.

**Rejected alternatives:**

- Adding separate high-water columns to `runtime_providers` and `agent_runtimes` was rejected because it duplicates allocation behavior, couples connection authority to two different lifecycle and deletion models, and risks conflating allocated generations with observed `provider_generation` and `runner_generation`.
- Using Provider connection-history maximum plus `agent_runtimes.runner_generation` directly was rejected because those projections are written at different lifecycle boundaries and do not represent one uniform allocation authority.
- A global sequence or random token was rejected because current fencing and durable state contracts require per-subject monotonic numeric generations, and changing that meaning would broaden protocol and persistence scope without solving subject-current ordering.

### redis-260907/ADR-D2: Use one-shot volatile candidates with final durable acceptance

**Affected requirements:** `redis-260907/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-8`

Registration crosses PostgreSQL and Redis through separate committed phases. No database transaction remains open across Redis, HTTP, gRPC, filesystem, object-storage, or other external I/O.

Runtime Control first validates the subject and allocates generation `g` from the D1 high-water relation in one short database-only transaction. The committed high-water retains `g` even when every later phase fails. Outside that transaction, Control stages the complete proposed connection record under a generation- and random-token-specific volatile candidate key with a short TTL. Candidate records are not visible to routing, heartbeat, dispatch, reports, results, or close handling.

A second database-only transaction verifies that `g` is still the subject high-water and that current registration authority remains eligible. After that transaction ends, one atomic coordination-store operation reads and consumes the exact stored candidate and promotes it into the subject's current connection record with the normal connection TTL. Promotion cannot reconstruct a missing candidate from arguments and refuses to replace a currently visible higher generation.

A final database-only acceptance transaction advances durable `accepted_generation` to `g` only while `g` is still the high-water and current authorization remains valid. Provider connection history, credential use, binding state, and matching audit evidence commit in this same transaction. Runner acceptance revalidates the current Runtime and credential authority without adding a second Runner connection-history entity.

If acceptance loses a race or authorization changes, Control ends the transaction before attempting exact-generation volatile revoke. Failed cleanup is bounded by the current-record TTL and cannot remove a higher generation. Only a committed acceptance permits relay tasks to start and `register_accepted(g)` to be emitted.

Stage or promotion commands whose outcome is unknown are never replayed as success and never retried with the same publication capability. The registration fails, the issued generation remains consumed, and a fresh registration receives a higher generation. Replacing Redis with an empty instance destroys candidates and current records; no pre-reset publication capability can be reconstructed from PostgreSQL.

A delayed lower-generation promotion after an empty-store reset may temporarily replace routing before final acceptance rejects it and cleanup or TTL removes it. The lower client has not received the generation and its relay loop has not started, so it cannot send an accepted heartbeat, report, result, operation, or revoke. The effect is bounded fail-closed unavailability rather than stale authority.

**Rejected alternatives:**

- Holding a database transaction or row lock across volatile publication was rejected because every external call inside a database transaction is forbidden.
- A database precheck followed by direct current-record publication was rejected because an empty Redis instance has no comparison floor and a delayed lower publisher can win after the check.
- Redis-only maximum-generation comparison was rejected because Redis replacement removes the maximum.
- PostgreSQL session advisory locks or expiring durable leases around Redis I/O were rejected as the primary protocol because they pin database coordination to external latency and still require a final durable acceptance rule for ambiguous delayed commands.
- Moving every live connection, operation, Transfer, and Terminal fence into PostgreSQL was rejected because the candidate protocol preserves safety with bounded fail-closed interruption while retaining Redis as the volatile live-routing and bounded-operation store. The durable-hot-path alternative would add outbox/inbox recovery, materially more database load, and a much broader state migration.

### redis-260907/ADR-D3: Seed migration-time Home subjects into a safe numeric band and use a strict namespace cutover

**Affected requirements:** `redis-260907/REQ-1`, `REQ-2`, `REQ-3`, `REQ-6`, `REQ-7`, `REQ-8`

Home is the only deployment that can contain legacy Redis-issued Provider or Runner connection generations. After every legacy Runtime Control replica has stopped, one table-locked migration transaction creates the allocator schema, seeds only Provider and Runtime subjects that exist at that migration boundary, installs database-enforced generation-row creation for future subjects, and records an immutable allocator cutover marker.

Each migration-time subject receives `high_water_generation = max(2^48 - 1, accepted_generation)`. Provider accepted evidence is the maximum durable `runtime_provider_connections.generation`, or zero when absent. Runner accepted evidence is `agent_runtimes.runner_generation`, or zero when absent. The first post-cutover allocation is therefore normally `2^48` (`281474976710656`), far above any plausible generation volume for the single Home legacy deployment even if Redis is already empty.

Subjects created after the cutover are not seeded into the legacy-safe band. `AFTER INSERT` triggers on the Provider and Agent Runtime subject tables create the matching `0/0` generation row inside the subject-creation transaction, so the first allocation receives generation one. The migration installs these triggers before releasing the table locks, closing the race with subject-creation transactions that began before the migration but insert only after it commits. Allocation never infers migration membership from timestamps and never lazily creates a missing row; any missing generation row is an allocator integrity error and fails closed. Generation rows survive subject disablement, Runtime stop or removal, connection expiry, and subject-row deletion so an identity never re-enters through a lower initialization rule.

PostgreSQL stores allocated and accepted generations as signed `BIGINT`. The allocator fails closed at `2^63 - 1` without wraparound, reset, random fallback, or generation reuse. The existing protobuf remains `uint64`; Redis and public JSON representation are decided separately in D4.

Runtime Control uses a one-time strict non-overlapping cutover. Home scales Runtime Control to zero and confirms legacy endpoints are absent before applying the migration and deploying the new version. The cutover procedure temporarily disables Runtime Control HPA and PDB constraints that would prevent zero replicas, then restores normal rolling deployment configuration after the new version is active.

The new version uses a fresh versioned Runtime coordination namespace for connection candidates and current records, request/reply/body streams, operation metadata, metrics, consumer groups, cursors, and other keys owned by the Runtime Coordination Store. It never reads, writes, imports, seeds, or deletes the legacy namespace. Runtime Transfer and Terminal keep their independently owned namespaces and existing empty-store recovery contracts.

Before the first new-band acceptance, deployment may return to the legacy release by restoring the pre-cutover procedure. After any new-band generation commits final acceptance, the transition is roll-forward-only: a legacy allocator must not restart, and PostgreSQL recovery must not move generation authority behind accepted evidence.

**Rejected alternatives:**

- Seeding from durable maxima alone was rejected because Runner authority may have been returned before any durable Runner report.
- Requiring a Redis counter import was rejected because migration must succeed when Redis is already empty.
- Seeding every future subject into the high band was rejected because a newly generated post-cutover identity has no legacy authority to collide with.
- Classifying an absent row from `subject.created_at > cutover_at` was rejected because PostgreSQL transaction timestamps can predate a migration lock even when the blocked insert occurs only after cutover.
- Updating every subject-creation service and quiescing all such writers was rejected because database triggers provide one atomic invariant without expanding the outage beyond Runtime Control.
- A rolling mixed-version transition was rejected because legacy and new replicas would issue from different authorities and operate different namespaces concurrently.
- Permanently changing Runtime Control to a `Recreate` deployment strategy was rejected because the outage is a one-time Home migration procedure, not the desired behavior for later releases.
- Reusing or synchronously deleting the legacy namespace was rejected because correctness must not depend on retained Redis state or its cleanup.
- Limiting the allocator to JavaScript's safe-integer range was rejected because string-safe JSON representation preserves the full positive signed `BIGINT` domain without turning a browser limitation into durable authority.

### redis-260907/ADR-D4: Represent JSON-exposed connection generations as canonical decimal strings

**Affected requirements:** `redis-260907/REQ-2`, `REQ-3`, `REQ-7`, `REQ-8`

Provider and Runner connection generations remain positive integers in PostgreSQL, Python, and existing protobuf `uint64` fields. Every JSON contract that stores, transports, or exposes one of those connection generations represents it as a canonical decimal string.

Redis-internal Runtime coordination records use a fixed-width 19-digit zero-padded decimal string. Equality uses exact string comparison, and ordering uses lexicographic comparison because every valid value has equal width. Lua never decodes or re-encodes a connection generation as a JSON number. Python converts between the internal fixed-width representation and validated positive signed `BIGINT` integers at the store boundary.

Public and browser-facing JSON uses an unpadded canonical decimal string. This covers Runtime raw-state diagnostics, Terminal WebSocket messages, and any other OpenAPI or JSON schema discovered by the implementation audit to carry a Provider or Runner connection generation. TypeScript treats the value as an opaque string and performs exact equality rather than numeric arithmetic.

The coordinated application cutover changes OpenAPI schemas and generated clients from numeric to string generation fields. It does not add numeric-and-string unions, duplicate legacy fields, version negotiation, or permanent compatibility parsing. The strict deployment and fresh Runtime coordination namespace from D3 update producers and consumers together.

**Rejected alternatives:**

- Keeping JSON numbers was rejected because Redis Lua cjson cannot re-encode the migration band exactly and JavaScript cannot exactly represent the full allocator domain.
- Limiting all generations to Redis cjson's 14-digit output range was rejected because it would make one volatile serializer a durable allocator constraint and materially reduce the future fencing domain.
- Changing only values above a threshold to strings was rejected because a union type would add a permanent value-dependent compatibility mode.
- Removing generation from Runtime and Terminal JSON contracts was rejected because exact diagnostics and Terminal authority checks remain useful and would require a broader interface redesign.


## Consequences

- Connection generation becomes a small durable fencing authority rather than retained Redis state.
- Provider and Runner registration share one allocation authority while retaining their separate authentication and observed-state models.
- Generation rows intentionally outlive volatile connection data and subject lifecycle transitions.
- Redis and in-memory coordination consume externally allocated generations and expose invisible candidate staging plus exact one-shot promotion.
- Registration can consume generations without returning them, and gaps are expected.
- A promoted registration that loses final acceptance can briefly interrupt routing, but it cannot grant stale authority.
- Migration-time Home subjects normally resume at generation `2^48`, while later identities start at one.
- Generation storage widens to `BIGINT`; protobuf remains `uint64`; Redis uses fixed-width decimal strings; public JSON and TypeScript use unpadded opaque decimal strings.
- Runtime Control requires one planned non-overlapping cutover and a fresh coordination namespace; legacy Redis state becomes ignored disposable data.

## Risks

- A polymorphic subject key cannot rely on one database foreign key. Registration authorization and bounded identifier validation must prevent invalid rows.
- Candidate and current-record TTLs must bound every crash and cleanup path without expiring an accepted stream before its first heartbeat.
- Provider durable history and accepted-generation evidence must commit atomically so a rejected credential cannot retain accepted volatile authority.
- Runner authorization must be revalidated in the final acceptance transaction without introducing a competing Runner history authority.
- The Home database maximum could not be independently queried because the provided read-only credential was rejected; the conservative floor relies on the confirmed single-deployment boundary rather than Redis or database maxima.
- The migration must serialize its subject snapshot against concurrent Provider or Runtime creation so a legacy-capable subject cannot be omitted.
- Subject-creation triggers become part of the allocator integrity boundary and must be present before the cutover marker permits new Runtime Control readiness.
- Every persisted field that directly stores a Provider or Runner connection generation must accept the new band, while unrelated desired, configuration, owner, and stream generations retain their existing domains.
- Every Redis Lua and JSON boundary that carries a Provider or Runner connection generation must preserve the canonical string representation; an unnoticed numeric conversion could corrupt fencing.
- Runtime Control must fail readiness on missing or incompatible cutover authority, and operators must not restart a legacy image after first new-band acceptance.
