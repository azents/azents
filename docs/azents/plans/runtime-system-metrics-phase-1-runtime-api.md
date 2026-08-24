---
title: "Runtime System Metrics Phase 1 Runtime Pipeline and Public API"
created: 2026-08-24
updated: 2026-08-24
tags: [runtime, metrics, implementation, api]
---

# Runtime System Metrics Phase 1 Runtime Pipeline and Public API

## Phase Execution Plan

- Phase: `1/2 — Runtime pipeline and Public API`
- Branch/base: `feat/runtime-system-metrics-1-runtime-api` → `origin/main@62ac03598`
- PR boundary: Runner collection through the dedicated Agent-authorized Public API
  and generated clients, without product UI or Living Spec promotion.
- Inputs: confirmed `runtime-260824/REQ`, accepted `runtime-260824/ADR-D1` through
  `ADR-D7`, approved `runtime-260824/DESIGN` revision `1`, and current Runtime
  persistence/Workspace Specs.
- Deliverables: M1–M6 and M8 Runtime collector, scheduler, protocol, Control
  admission, volatile series, service, endpoint, generated Public clients, and
  deterministic focused tests.
- Non-goals: M7 product UI, tRPC consumption, stories, browser E2E, Spec promotion,
  implementation markers, or plan cleanup; Provider, PostgreSQL, migration, chart,
  RBAC, Admin, configuration, push, alerting, or lifecycle-response work.
- Interfaces:
  - optional capability `runtime.system-metrics.v1`;
  - additive `RunnerMessage.system_metrics` protobuf payload with no Runner timestamp
    or free-form metadata and an explicit maximum serialized size of 4 KiB at
    admission;
  - typed normalized shared sample with scope `host|vm|container`, availability
    `available|unavailable|unsupported`, positive sequence, nonnegative usage, and
    positive optional totals;
  - Coordination Store append/read keyed by Runtime ID and physical Runner connection
    generation, with atomic higher-sequence admission, maximum 60, and one-hour
    retention/filtering;
  - `GET /agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/system-metrics`
    using the existing Agent access boundary and a privacy-safe response whose
    overall-summary enum is exactly `fresh|partial|stale|unavailable|unsupported|
    stopped|disconnected`;
  - generated Python and TypeScript Public clients as the only downstream API contract.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M8`
- Authority references: `runtime-260824/REQ-1` through `REQ-6`;
  `runtime-260824/ADR-D1` through `ADR-D7`; `runtime-260824/DESIGN` revision `1`;
  Agent Runtime Persistence Spec; Workspace Spec; Redis optionality and deterministic
  test project conventions.
- Design delta: `None`
- Removal obligations: None; the feature is additive. Preserve the existing Runner
  protocol version/required transfer capability, Provider contracts, PostgreSQL
  schema, lifecycle reconciliation, Agent Workspace authority, and
  `AgentRuntimeResponse`.
- Absence verification: inspect the final diff and search Provider/chart/migration/
  model/lifecycle response paths; assert the new Public metrics response and raw
  metric sample logs contain no Runtime/Runner/Provider/connection/generation/host/
  path/mount/device/process identifiers. Existing bounded internal correlation fields
  may remain in warning/error logs. Confirm there is no alternate or legacy metrics
  path.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared protocol and generation | `/root` | `proto/azents/runtime_control/v1/runtime_runner_control.proto`; `python/libs/azents-runtime-control/**` | Approved M2/M3 contract | Capability constant, closed models, protobuf conversion, generated modules, client send operation | Runtime-control format/lint/type/unit tests; generated diff; 4 KiB boundary/rejection; old/new payload compatibility test |
| Runner collector and scheduler | `/root` | `python/apps/azents-runtime-runner/**` | Shared protocol | Injected Linux collector and immediate/60-second generation-local reporting loop | Collector fixtures; fake clock/event scheduler tests; Runner format/lint/type/unit tests |
| Coordination Store | `/root` | `python/apps/azents/src/azents/runtime/coordination/**` | Shared sample model | Typed Redis and memory higher-sequence ring with equivalent retention | Both-backend contract tests, injected time, concurrent ordering, trim/filter/expiry/empty restart |
| Control admission | `/root` | `python/apps/azents/src/azents/runtime/control_protocol/**`; `python/apps/azents/src/azents/runtime/control_server.py` | Protocol and store | Current generation/capability validation, server UTC assignment, isolated append failure | gRPC and protocol tests for invalid/stale/duplicate reports, stream/lifecycle isolation |
| Metrics read service | `/root` | `python/apps/azents/src/azents/services/agent_runtime_system_metrics/**`; required dependency providers | Store and existing Agent Runtime read | Exact generation selection and server-derived state/percentage/overall-summary projection | Service tests for access, current/disconnected generation, every mixed-state summary branch, overlays, 3-minute edge, no fallback/privacy, and store-read failure isolation |
| Public API and generated clients | `/root` | `python/apps/azents/src/azents/api/public/agent_runtime/v1/**`; OpenAPI output; `python/libs/azents-public-client/**`; `typescript/packages/azents-public-client/**` | Metrics service | Dedicated route and source-generated clients without lifecycle response edits | Route/schema/auth tests; OpenAPI dump; Python/TypeScript generation and checks |
| Documentation and integration | `/root` | approved snapshot docs; `docs/azents/plans/**` | All workstreams | Current tracked execution checkpoint with no Spec promotion | Docs index/check, `git diff --check`, authority and absence audit |

- Integration order:
  1. Add shared models/protobuf fields and regenerate protobuf code.
  2. Implement collector and scheduler against the shared client operation.
  3. Add store data/protocol and Redis/memory implementations with contract tests.
  4. Add Control admission and failure isolation.
  5. Add the dedicated service, API response models, route, and authorization tests.
  6. Regenerate OpenAPI and both Public clients.
  7. Run focused checks, integrated Phase 1 checks, drift/absence audit, and
     independent review.
- Independent review: `runtime-metrics-reviewer` reviews the complete stable Phase 1
  diff read-only against Requirements, ADR-D1–D7, Design M1–M6/M8, this phase
  contract, privacy/security boundaries, generation correctness, Redis/memory parity,
  compatibility, state precedence, validation evidence, and unauthorized additions.
  Output is a concise findings list; only requirements/design, security/data-loss,
  material convention/interface corrections require targeted re-review.
- Final validation:
  - `cd python/libs/azents-runtime-control && uv run python scripts/generate_proto.py`
  - Runtime-control Ruff, configured type checker, and focused/full unit tests.
  - Runtime Runner Ruff, configured type checker, and focused/full unit tests.
  - Backend coordination, Control gRPC/protocol, service, route, and schema tests,
    followed by affected Ruff and configured type checks.
  - `cd python/apps/azents && uv run python src/cli/dump_openapi.py`
  - `cd python/libs/azents-public-client && make generate`
  - `cd typescript && pnpm run generate --filter=@azents/public-client`, followed by
    affected format/lint/type checks.
  - docs index/check, snapshot validator tests, and `git diff --check`.
- Scope-drift check:
  - approved coverage: M1–M6 and M8 are implemented and tested;
  - missing coverage: no approved Phase 1 behavior or compatibility/absence evidence
    is omitted;
  - unauthorized additions: no M7 UI, Provider, database, configuration, Admin,
    infrastructure, lifecycle-authority, second-contract, push, or legacy fallback.
- Context checkpoint: complete on 2026-08-24.
  - Implemented interfaces: optional Runner capability
    `runtime.system-metrics.v1`; additive `RunnerMessage.system_metrics` with Runtime
    ID, positive generation-local sequence, closed scope/availability values, and
    CPU/memory/disk observations; dedicated
    `GET /agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/system-metrics`
    response with only summary, scope, current metric projections, and retained
    samples.
  - Runner behavior: Linux cgroup v1/v2 or host-visible collection, conservative
    host/VM/container scope, unavailable first CPU sample, immediate report, and
    generation-local 60-second cadence. Non-Linux and unavailable sources remain
    explicit without Provider or node substitution.
  - Control and store behavior: current connection generation and advertised
    capability fence admission; the server assigns UTC acceptance time; invalid,
    stale, duplicate, lower-sequence, or larger-than-4-KiB reports are dropped without
    closing the stream. Redis and memory atomically retain at most 60 samples for one
    Runtime/generation key, refresh one-hour expiry, and filter measurements older than
    one hour.
  - Read behavior: connected reads select only the current connection generation and
    never fall back; disconnected reads may select only the durable last-known Runner
    generation. The latest observation controls each current metric, three minutes is
    the inclusive freshness boundary, stopped/disconnected overlays preserve retained
    trends, and mixed overall summaries follow the approved precedence.
  - Compatibility and generation: an executable previous-schema protobuf test proves
    an old parser ignores the additive unknown metrics oneof and continues with the
    next known heartbeat. Reconnection starts a new empty series.
  - Generated artifacts: regenerated Public OpenAPI and tracked Python client models,
    operation, docs, and tests. The gitignored TypeScript generated client was
    regenerated from the same OpenAPI source and passed Prettier and TypeScript checks.
  - Validation: Runtime Control Ruff/type/full tests (`123 passed`); Runtime Runner
    Ruff/type/full tests (`176 passed`); focused backend boundary tests (`107 passed`)
    before the test-only review correction; complete backend tests (`4697 passed`);
    corrected metrics service/API tests (`16 passed`); previous-schema compatibility
    file (`16 passed`); Python generated-client import/compile; TypeScript generated
    client format/typecheck; docs index check; OpenAPI privacy schema inspection; and
    `git diff --check`.
  - Review and drift: `runtime-metrics-reviewer` approved the corrected stable diff
    with no remaining findings and no further targeted re-review required. The absence
    audit found no Provider, PostgreSQL, migration, chart, Admin, product UI,
    configuration, alternate metrics path, or lifecycle-response expansion.
  - Remaining scope and risk: Phase 2 still owns generated-client-backed web tRPC,
    shared responsive UI/stories, repository Docker Runtime browser E2E, Living Spec
    promotion, implementation markers, and plan cleanup. Metrics remain volatile and
    informational; Redis loss or endpoint failure cannot affect Runtime lifecycle or
    ordinary Runner operations.

## Derived Execution Details

These details resolve approved contracts without creating new authority:

- Connected API reads first obtain the current Runner `RuntimeConnectionRecord` and
  require its metadata capability before reading that exact generation. When no
  current connection exists, the service may use only the durable Runtime
  `runner_generation` as last-known disconnected history. It never probes another
  generation.
- The latest sample controls each metric even if that sample is unavailable or
  unsupported. Older available samples remain trend entries only.
- Current-state precedence is `stopped`, then `disconnected`, then latest observation:
  `unsupported`, `unavailable`, or available `fresh|stale`. A capable generation with
  no sample is unavailable. Runtime capability absence is unsupported.
- Overall-summary projection is deterministic:
  - `stopped` when the Runtime lifecycle summary is stopped;
  - else `disconnected` when there is no current Runner connection;
  - else `fresh` when CPU, memory, and disk are all fresh;
  - else `partial` when at least one metric is fresh;
  - else `stale` when at least one metric is stale;
  - else `unavailable` when at least one metric is unavailable;
  - else `unsupported` when all three metrics are unsupported.
- A successfully empty store read maps to an empty overview. A raised store read error
  propagates only from this endpoint; a direct route test also proves the existing
  lifecycle route remains successful with the same failing store. A raised append
  error is logged with a stack trace and drops only that sample.
- Scope classification must be conservative: explicit usable cgroup evidence permits
  `container`; explicit virtualization evidence may permit `vm`; otherwise a
  non-container Linux environment is `host`. Ambiguous or unreadable sources must not
  substitute node/Provider scope and instead produce unavailable/unsupported metric
  observations under the safely established environment scope.
- Compatibility with an old server is an executable claim, not an assumption. If the
  current gRPC bridge closes or errors on an unknown additive oneof payload, stop and
  return to Design rather than adding a second wire format or protocol fallback.
- Message size is bounded independently of the server's general gRPC defaults:
  admission rejects a serialized system-metrics payload larger than 4 KiB without
  closing the stream, and tests cover the exact boundary plus rejection.
