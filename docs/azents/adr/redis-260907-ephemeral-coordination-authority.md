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
- [x] `redis-260907/ADR-D2` — Use one-shot Redis candidates with DB-only preflight and acceptance transactions.
- [x] `redis-260907/ADR-D3` — Seed only migration-time subjects into a Home-bounded legacy-safe generation band and use a strict namespace cutover.
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

### redis-260907/ADR-D2: Use one-shot Redis candidates with DB-only preflight and acceptance transactions

**Affected requirements:** `redis-260907/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-8`

Registration uses committed database state and one-shot volatile publication capabilities. No database transaction remains open across a Redis call.

Runtime Control first allocates and commits a generation from the D1 high-water relation in one short database-only transaction. It then stages the complete connection record under a generation- and token-specific Redis candidate key with a short TTL. Candidate records are not routing records. After staging, a second short database-only transaction confirms that the candidate generation is still the subject high-water. A stale candidate stops before promotion.

Outside that transaction, one atomic Redis operation promotes only the stored candidate record into the subject's current-connection key when no higher current generation exists. The promotion operation must read and consume the candidate key; it cannot reconstruct the candidate solely from call arguments. Replacing Redis with an empty instance therefore destroys every pre-reset publication capability as well as the old current connection.

After explicit promotion success, a final short database-only compare-and-set transaction accepts the generation only while it remains the high-water and advances durable accepted-generation evidence. Provider registration records its authenticated connection history in that same acceptance transaction. If the acceptance compare-and-set loses a race, Runtime Control attempts an exact-generation revoke only after the transaction has ended and rejects the registration. It emits `register_accepted` only after the acceptance transaction commits.

An allocation, candidate stage, promotion, acceptance, or response failure consumes the generation but never permits generation reuse. A Redis command with an uncertain outcome is not replayed as success and does not reuse the same publication capability. The client must reconnect through a fresh registration and receive a higher generation. Candidate and unacknowledged current records remain bounded by TTL, and exact-generation cleanup cannot revoke a newer connection.

Concurrent registrations may briefly replace routing before their final database acceptance. Until `register_accepted`, the registering client has not received the generation and its relay loop has not started; losing the final compare-and-set therefore produces a bounded fail-closed routing gap rather than published connection authority. Once a higher registration has completed promotion and durable acceptance, a lower delayed registration cannot become accepted after an empty Redis replacement: its pre-reset candidate is gone, while a candidate staged after the reset fails the durable high-water checks.

**Rejected alternatives:**

- Holding a row lock or transaction-scoped advisory lock while installing Redis state was rejected because external calls inside database transactions are forbidden.
- Allocating in PostgreSQL and directly writing a generation-maximized Redis current record was rejected because a newly empty Redis has no retained comparison floor and could accept a delayed lower publisher.
- Making PostgreSQL own the current live connection and requiring database validation on every heartbeat, route, and operation fence was rejected because Redis can remain the volatile live-routing authority with the candidate capability and durable acceptance boundary.
- Holding a PostgreSQL session advisory lock or expiring durable lease across Redis I/O was rejected because it pins database coordination to external latency and still needs stale-holder fencing after connection loss or lease expiry.

### redis-260907/ADR-D3: Seed only migration-time subjects into a Home-bounded legacy-safe generation band and use a strict namespace cutover

**Affected requirements:** `redis-260907/REQ-1`, `REQ-2`, `REQ-3`, `REQ-6`, `REQ-7`, `REQ-8`

The cutover does not depend on reading or restoring legacy Redis counters. The requester confirmed that Home is the only legacy deployment and delegated selection of a conservative cutover floor below `2^63`. The migration inserts D1 high-water rows for every Provider and Runtime subject that exists at migration time and seeds their high-water at `2^48 - 1` (`281474976710655`). Their first post-cutover allocation therefore begins at `2^48` (`281474976710656`). This is far above the bounded generation volume that the single 2026 Home deployment could have issued while remaining comfortably inside PostgreSQL signed `BIGINT`.

Subjects created after the migration are not seeded into the legacy-safe band. Their absent high-water row is initialized at zero and their first generation is one because their newly generated immutable subject identity has no pre-cutover connection authority. High-water rows remain after later subject lifecycle transitions, as required by D1, so a migrated or newly created identity never falls back to another initialization rule.

The generation persistence boundary uses signed `BIGINT` and fails closed before overflow rather than wrapping or reusing authority. Redis records encode connection generations in one canonical fixed-width or otherwise order-preserving decimal string representation, and Lua scripts compare that representation without converting it to a Lua number. The protobuf remains `uint64`, but this allocator intentionally uses its positive signed 64-bit subset.

Runtime Control uses a strict cutover rather than a rolling mixed-version period. All legacy Runtime Control replicas stop accepting and serving streams before schema migration and new-version startup. The migration seeds the existing subjects and establishes the allocator schema. Only then may new Runtime Control replicas become ready. Existing Provider and Runner streams disconnect and reconnect through the new allocator.

The new Runtime Control version uses a fresh Redis coordination namespace for connection candidates, current connections, request/reply/body streams, operation metadata, system metrics, and consumer-group state. It never reads, seeds, writes, or falls back to the legacy connection-generation counters or coordination namespace. Legacy volatile keys may expire naturally or disappear with the disposable Redis instance; their deletion is not a correctness prerequisite.

Startup fails closed when the database schema or allocator cutover marker is not compatible with the new allocator. The deployment boundary must prevent legacy and new Runtime Control binaries from serving concurrently; the current default rolling Deployment behavior is not retained for this transition.

**Rejected alternatives:**

- Seeding every future subject into the high generation band was rejected because a subject identity created after migration has no legacy authority to fence; new subjects retain the natural first generation of one.
- Backfilling from Provider history, Runtime projections, and a one-time import of Redis counters was rejected because an already-empty Redis cannot reveal a Runner generation that was accepted but not yet reported durably.
- A rolling mixed-version transition with temporary dual reads or writes was rejected because legacy replicas could continue issuing Redis generations and would preserve two competing allocation and namespace authorities.
- Reusing the legacy Redis namespace and deleting selected keys was rejected because old streams, operations, current records, consumer groups, and counters could be mistaken for post-cutover volatile state.

### redis-260907/ADR-D4: Represent JSON-exposed connection generations as canonical decimal strings

**Affected requirements:** `redis-260907/REQ-2`, `REQ-3`, `REQ-7`, `REQ-8`

Provider and Runner connection generations remain positive integers in PostgreSQL, Python, and the existing protobuf `uint64` fields. Every public or browser-facing JSON contract that exposes one of those connection generations represents it as a canonical decimal string. TypeScript treats the value as an opaque string and performs exact equality rather than numeric arithmetic.

This coordinated contract change covers the public Runtime raw-state projection, Terminal WebSocket messages, and any other JSON schema discovered by the implementation audit to carry a Provider or Runner connection generation. OpenAPI schemas and generated clients change from numeric to string types in the same cutover. Internal JSON stored in Redis uses the same canonical string rule for exact Lua fencing.

The cutover does not add numeric-and-string unions, duplicate fields, version negotiation, or permanent compatibility parsing. The strict Runtime Control and application deployment boundary from D3 updates producers and consumers together.

**Rejected alternatives:**

- Keeping JSON numbers was rejected because JavaScript cannot exactly represent the full allocator domain and two distinct future generations could compare equal after numeric conversion.
- Changing only values above the JavaScript safe-integer limit to strings was rejected because a union type would add a permanent compatibility mode and value-dependent parsing.
- Removing generation from the Runtime and Terminal contracts was rejected because those diagnostics and exact Terminal authority checks remain useful and would require a broader interface redesign.

## Consequences

- Connection generation becomes a small durable fencing authority rather than retained Redis state.
- Provider and Runner registration use one allocation contract while preserving their separate authentication and observed-state models.
- Generation rows intentionally outlive volatile connection data and require bounded lifecycle and integrity handling.
- Redis coordination implementations accept an externally allocated generation and expose candidate staging and promotion instead of allocation.
- Migration-time subjects enter the `2^48` generation band, while later new identities retain generation one as their natural first value.
- JSON and browser contracts carry connection generations as decimal strings while protobuf retains `uint64`.
- Runtime Control requires one bounded strict cutover and cannot roll back to the legacy allocator after a new-band generation is accepted.
- Legacy Redis Runtime coordination data is ignored rather than migrated, interpreted, or synchronously deleted.

## Risks

- A polymorphic subject key cannot rely on one database foreign key. Registration authorization and bounded identifier validation must prevent invalid rows.
- The requester-approved `2^48` floor relies on the confirmed single Home legacy deployment rather than a mathematical bound over every possible Redis signed integer; implementation evidence must verify all observable legacy maxima remain below the floor.
- Connection generation requires signed `BIGINT` storage and exact string-safe JSON/Redis comparison; any remaining 32-bit or floating-point boundary could corrupt fencing.
- Candidate promotion before final database acceptance can create a short fail-closed routing gap. Exact cleanup, TTL, and fresh higher registration must bound it without reporting success.
- The strict cutover intentionally disconnects all Provider and Runner streams and requires deterministic deployment ordering before new replicas become ready.
- A missing high-water row for a subject that existed at migration time must fail closed; initializing it at one would reintroduce legacy collision risk.
