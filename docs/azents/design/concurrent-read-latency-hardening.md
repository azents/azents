---
title: "Concurrent Read Latency Hardening"
created: 2026-07-19
updated: 2026-07-19
implemented: 2026-07-19
tags: [backend, runtime, toolkit, performance, reliability]
document_role: supporting
document_type: supporting-consolidation
migration_source: "docs/azents/design/concurrent-read-latency-hardening.md"
supporting_role: consolidation
---

# Concurrent Read Latency Hardening

## Problem

One Agent Runtime is shared by multiple Agent Sessions. Under concurrent Session activity, model-visible `read` calls can pause for several seconds even when the requested file is small.

The latency comes from two compounding implementation defects:

1. Runtime Runner file handlers perform synchronous filesystem reads, stats, directory traversal, and regex scans on the Runner asyncio event loop. A large `file.list` or `file.grep` therefore delays unrelated operations after they have already been admitted by the fair Session scheduler.
2. Successful `read` calls trigger AGENTS.md and Claude Rules appendix hooks. These hooks repeatedly discover the same instruction paths, issue one Runtime RPC per stat/read, use the system owner instead of the invoking Session, and allow parallel reads to race before persistent dedupe state is updated.

The current behavior contracts remain correct: applicable instruction content is appended to successful `read` results, content is read fresh when appended, and dedupe resets on Session compaction. This design preserves those contracts while removing event-loop blocking and redundant internal work.

## Goals

- Keep the Runner event loop responsive while file operations perform blocking filesystem work.
- Bound filesystem worker concurrency independently from ordinary Runner operation concurrency.
- Avoid repeated instruction-root discovery and absent AGENTS.md probes during bursts of reads.
- Filter already-appended candidates before stat/read RPCs.
- Serialize same-Session appendix discovery and dedupe updates so parallel reads do not repeat expensive work or append the same instruction twice.
- Attribute all model-visible and appendix-internal file operations to the invoking Agent Session.
- Reuse one ready Runtime snapshot across the visible file tool and its appendix hooks.
- Expose structured latency and internal-RPC diagnostics for the visible handler and appendix phases.
- Preserve existing model-visible output, failure isolation, instruction ordering, content caps, and compaction reset behavior.

## Non-goals

- Raising the Runner ordinary operation limits as a latency solution.
- Caching AGENTS.md or Claude rule content.
- Changing which instruction files apply to a path.
- Appending instructions to tools other than successful `read`.
- Changing Toolkit State schema or introducing a new durable cache.
- Adding cross-Runtime or cross-process cache infrastructure.
- Changing Runtime lifecycle or authorization semantics.

## Current Behavior

### Runner filesystem execution

`RunnerOperations` handles many admitted operations concurrently, but `file.read`, `file.stat`, `file.list`, and `file.grep` execute `pathlib`, recursive traversal, file decoding, and regex work synchronously inside their async handlers. The Session scheduler can fairly start an unrelated operation, but that operation cannot make progress while another handler blocks the single event loop.

### Appendix discovery

AGENTS.md loading computes a short candidate chain, then performs `file.stat` and `file.read` sequentially for each candidate. Missing candidates are probed again on every later read.

Claude Rules loading recursively lists each applicable `.claude/rules` root on every read, then stats and reads every discovered Markdown file before persistent path dedupe is applied. Parallel tool calls execute as separate tasks, so each call can observe the same pre-update Toolkit State and repeat discovery and content reads.

`RuntimeRunnerFileStorage` creates a new Runtime lookup for every operation and currently sends `owner_session_id=None`, placing appendix work and visible file tools in the shared system queue even though they belong to a Session.

## Proposed Design

### 1. Bounded non-blocking Runner filesystem execution

Runner owns a dedicated bounded filesystem executor. Direct filesystem handlers submit their complete blocking section to that executor and await the result from the asyncio loop. The initial boundary covers read, write, stat, list, grep, delete, mkdir, move, and bulk file mutations. Async process and Git subprocess streaming remain on the event loop.

The executor has a fixed conservative worker bound. It is not a replacement for Runner admission limits: ordinary Session/system/Runtime limits remain authoritative, while the executor limits simultaneous blocking filesystem work after admission.

Traversal and grep helpers accept a thread-safe cancellation signal. If the async handler is cancelled, it sets the signal; recursive traversal and line scanning check it at bounded intervals and stop promptly. Python cannot forcibly interrupt a filesystem syscall already running in a worker thread, so cancellation guarantees are cooperative between blocking calls rather than preemptive inside the operating system.

Existing file result payloads and typed error mappings remain unchanged.

### 2. Session-local instruction discovery cache

Instruction toolkits keep only discovery metadata in process memory:

- AGENTS.md caches candidate existence, including negative results, for a short bounded TTL.
- Claude Rules caches the sorted Markdown path list for each supported rules root for a short bounded TTL.
- Content bytes, parsed frontmatter, match results, and rendered appendices are not cached.

The cache lifetime smooths bursts of concurrent and sequential reads while allowing newly created instruction files to become visible shortly without an explicit invalidation protocol. Compaction clears persistent append dedupe and local discovery caches together.

A cache miss performs the existing Runtime discovery operation. A cache hit skips only discovery RPCs. Every candidate selected for a new appendix is still statted and read at append time, preserving fresh content and symlink safety.

### 3. Singleflight and pre-I/O dedupe

Each appendix toolkit owns an asyncio lock scoped to its Session-managed toolkit instance. The complete sequence runs under the lock:

1. reload persistent dedupe state;
2. compute candidates and remove already-appended paths;
3. discover only when the local discovery cache misses;
4. stat/read only remaining candidates;
5. update persistent dedupe state;
6. render the appendix.

This serializes parallel reads in one Session before expensive I/O. The second caller reloads state after the first caller commits and therefore skips already-appended paths before discovery reads.

The existing Toolkit State compare-and-set update remains the durable protection across retries and worker replacement. The process-local lock addresses the normal same-worker task race without introducing a distributed lock.

### 4. Session ownership and Runtime snapshot reuse

`RuntimeRunnerFileStorage` requires an explicit nullable `owner_session_id`. Runtime file tools construct it with the invoking Runtime Session ID. Agent-level callers may still deliberately pass `None` when they instantiate storage outside a Session.

The storage instance lazily resolves a ready Runtime once and reuses that immutable ID/generation snapshot for its lifetime. Runtime Toolkit creates one storage instance per turn and shares it with the visible file tools and instruction hooks, so one visible read and its appendices do not repeatedly query Runtime readiness. Generation and availability failures continue to surface through existing operation errors; there is no fallback to a different generation inside an in-flight tool call.

### 5. Structured latency diagnostics

Diagnostics separate the phases that contribute to read latency:

- visible file tool operation duration and Runtime operation count;
- AGENTS.md hook duration, candidate count, cache hits/misses, dedupe skips, stat count, and read count;
- Claude Rules hook duration, root-list RPC count, discovered path count, cache hits/misses, dedupe skips, stat count, and read count;
- Runner filesystem queue wait in the dedicated executor and blocking execution duration.

Fields use Session/Runtime/request identifiers already permitted by existing operator logging policy. Raw file contents and tool output are never logged.

No new model-visible diagnostics are added.

## Error Handling

- Runtime/FileStorage communication failures keep the existing appendix fail-open behavior.
- `asyncio.CancelledError` propagates and triggers the cooperative filesystem cancellation signal.
- Missing AGENTS.md files and missing Claude rule roots remain quiet configuration misses.
- Cache state is an optimization only. Cache corruption or expiration falls back to discovery and cannot replace Toolkit State as dedupe authority.
- A stale Runtime generation fails through the existing operation failure path; storage does not silently retry a potentially non-idempotent mutation against a replacement Runner.

## Security and Permissions

Session ownership is trusted scheduling context, not authorization evidence. Existing service authorization and workspace path validation remain unchanged.

Instruction discovery continues to enforce registered Project boundaries, real-path owner-root containment for Claude Rules, and existing workspace-root applicability. Cache keys contain normalized paths and do not store content or credentials.

## Rollout

The change is internal and requires coordinated server and Runtime Runner deployment only because both components receive code changes. No protocol, database, API, fixture credential, or migration change is required.

Rollout monitoring should compare:

- `read` tool p50/p95/p99 duration;
- appendix internal RPCs per successful read;
- Runner event-loop scheduling gaps while recursive file operations run;
- filesystem executor queue and execution durations;
- system-owned versus Session-owned file operation counts;
- appendix cache hit and dedupe-skip rates.

## Test Strategy

### Unit and component tests

- Runner file read/list/grep behavior remains byte-for-byte compatible.
- A deliberately blocked filesystem scan does not prevent an unrelated async Runner handler from progressing.
- Cancellation causes recursive traversal or grep to observe the cancellation signal and stop.
- Filesystem executor concurrency stays within its configured bound.
- AGENTS.md negative discovery cache avoids repeated stat RPCs within its TTL and refreshes after expiry.
- Claude Rules root discovery cache avoids repeated recursive list RPCs while still reading unappended content fresh.
- Parallel same-Session reads append each instruction path once and the losing call performs no duplicate stat/read work.
- Dedupe filtering occurs before candidate content I/O.
- Compaction clears persistent dedupe and local discovery caches.
- Runtime file operations propagate the invoking Session ID and reuse one ready Runtime lookup.
- Structured diagnostics report phase durations and operation counts without content.

### Integration validation

Use the existing Runtime operation clients and fake storage/toolkit harnesses. No external credentials are required. Deterministic barriers replace timing-only sleeps for concurrency assertions.

### E2E primary matrix

| Scenario | Expected result |
| --- | --- |
| Two Sessions concurrently read small files while one recursive scan is blocked | The unrelated read progresses without waiting for the scan to finish |
| One Session emits parallel reads under the same Project | Applicable AGENTS.md and Claude rules appear once per dedupe lifecycle |
| Repeated reads with no root AGENTS.md or rules directory | Internal discovery RPC count falls after the first read |
| Successful read with existing instructions | Output ordering, raw content, caps, and `<system-reminder>` rendering match current behavior |
| Subagent and root Session share one Runtime | Internal file operations carry their own Session IDs |
| Session compaction followed by read | Current instruction content is appended again |

The deterministic component matrix is the mandatory CI gate. A product-path E2E uses the existing Runtime fixture when available; lack of external credentials is never a skip reason. Evidence records commands, environment, test counts, and before/after internal operation counts.

### Fixture and prerequisite assessment

No new testenv seed, provider credential, or public test API is required. Existing fake Runner clients and file storage fixtures can expose deterministic barriers and operation counters. Docker-backed Runtime E2E remains useful as a regression check but does not replace component-level concurrency tests.

## Acceptance Criteria

- Blocking filesystem traversal no longer blocks the Runner asyncio event loop.
- Filesystem work is bounded independently from ordinary Runner admission.
- Same-Session parallel reads do not duplicate instruction appendices or their internal stat/read RPCs.
- Repeated absent instruction candidates and unchanged Claude rule roots use bounded discovery caches.
- Instruction content remains fresh whenever it is appended.
- Every Session-scoped file operation, including appendix work, uses the invoking Session owner.
- One read tool call and its hooks reuse one Runtime readiness snapshot.
- Production logs distinguish visible tool, appendix, executor queue, and blocking filesystem durations.
- Existing model-visible read and appendix behavior remains unchanged.

## Spec Impact

After validation, update:

- `docs/azents/spec/domain/toolkit.md` for discovery caching, singleflight, fresh-content, ownership, and diagnostics behavior;
- `docs/azents/spec/flow/agent-runtime-control.md` for non-blocking bounded filesystem execution and Session ownership of appendix-internal operations.

No ADR change is required because the design implements and hardens existing [deterministic-260628/ADR](../adr/deterministic-260628-deterministic-catalog-and-mcp-snapshots.md), [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-228), and [runner-260710/ADR](../adr/runner-260710-runner-operation-concurrency.md) contracts rather than replacing them.
