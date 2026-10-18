---
title: "Session Routines Phase 2 Judgment"
created: 2026-10-18
tags: [routine, implementation, plan]
---

# Phase Execution Plan

- Phase: 2 of 5, canonical Structured judgment and isolated observation.
- Branch/base: `feat/routine-261018-2-judgment` -> `feat/routine-261018-1-foundation` at `c925300a1`.
- PR boundary: purpose-owned model operation and typed event contracts, without Scheduler/ordinary execution activation.
- Inputs: [Requirements](../requirements/routine-261018-session-routines.md), [ADR](../adr/routine-261018-session-routines.md), [approved Design revision 1](../design/routine-261018-session-routines.md), [implementation plan](session-routines-implementation-plan.md), phase 1 [PR #2328](https://github.com/azents/azents/pull/2328).
- Approved Design mechanisms: `M3, M7, M11`.
- Authority references: REQ-7, REQ-11, REQ-16; ADR-D1/ADR-D3; existing provider capabilities, watchdog, normalization and transaction boundaries.
- Design delta: None.
- Deliverables: typed joint judgment input/result and identity validation; purpose-owned full canonical-history lowering with native Structured output and no callable tools; provider invocation/terminal proof/cleanup; dedicated typed judgment observation with call-specific model/usage; observation-only history/live/model-visible/token-estimate semantics; explicit generated event-client synchronization; focused tests.
- Non-goals: live Scheduler/tick activation, ordinary Routine admission/completion tools, Primary notification execution, inspection UI, new alternate judgment model/fallback, conversation freshness checks, ordinary turn markers or prompt snapshots for judgment.
- Interfaces: operation receives the ordinary Session canonical context basis plus candidate context; actual request has zero client/hosted executable tools and an explicit output schema. A result selects only supplied candidate identities. Failure is distinct from no-action. Usage belongs to the judgment operation, not a normal Run.
- Removal obligations: no flattened-text helper adapter for Routine history; no reuse of ordinary output admission/turn-marker side effects. Existing helper callers and normal lowerer behavior remain.
- Absence verification: captured provider request/history tests, no fabricated Run/turn_complete, unchanged normal context gauge/inspector/compaction and Session prompt snapshot paths.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Judgment contracts | /root | `core/routine_judgment*` | phase 1 domain types | typed candidates/decision/result validation | unit/schema tests |
| Provider integration | /root | `engine/events/{pydantic_ai_lowering,responses_lowering,protocols}*`, purpose-owned judgment operation, provider adapter helpers as required | canonical transcript and saved capabilities | Structured full-history request with no executable tools | both lowerers/dialects, SDK-wire/terminal/cleanup tests |
| Observation | /root | `core/enums.py`, `engine/events/types.py`, closed observation consumers, `repos/routine` observation operations, migration/revision | typed result | distinct observation persistence/live history with isolated usage | payload/ownership/usage/projection regressions |
| API/client coherence | /root | event public projections, source OpenAPI, source-generated Python/TS clients and Session core wire decode as required | event | exhaustive consumers, no raw metadata escape | OpenAPI generation, backend/TS type checks |
| Plans/evidence | /root | phase plans and relevant current Specs when actual existing behavior changes | stable integration | evidence and phase checkpoint | catalog, links, review |

Integration order: contracts -> lowerers and request validation -> actual model
operation boundary -> typed observation and explicit consumers -> migration/client
regeneration -> integrated regressions -> stable same-reviewer review -> root
corrections/checks -> commit and PR before phase 3.

Independent reviewer: `/root/routine-reviewer`, read-only review of the complete
stable phase diff after root implementation/validation. Root owns corrections and
all test execution.

Final validation: focused Ruff, full backend ty, deterministic provider contracts,
actual PostgreSQL event/migration tests, existing model_text/native lowerer and
context/compaction regressions, generated-client checks and applicable TypeScript
quality checks. Missing optional live credentials do not skip deterministic
coverage. No live provider success is inferred from fixture results.

Scope-drift check: confirm all changed mechanisms map to M3/M7/M11; no new model
configuration, retry, semantic history or execution authority. Return material
mechanisms or user-visible input-policy changes to design rather than adding
fallbacks.

Context checkpoint: phase 1 PR opened, root tests 330 passed and P2 fully closed by
the same reviewer. Backend and TypeScript frozen dependencies prepared. Full
product E2E and production Binding audit remain future verification gates. Phase
1 CI is not awaited before constructing the stack.

Initial implementation checkpoint, 2026-10-18 KST:

- Added typed joint candidates/decisions with explicit membership validation and
  a dedicated judgment observation carrying only its own nullable usage.
- Added Structured tool-free entrypoints to both canonical lowerers and the
  official OpenAI Responses envelope wrapper. Actual effective controls and
  saved capabilities are checked; ordinary conversation history remains
  structured rather than being flattened into a helper text argument.
- Explicitly excluded judgment observations from semantic provider input and
  model-visible token estimation. Added the purpose-owned model call kind.
- Generated migration `854782c43687` for the new event kind and updated revision;
  this migration has not yet been exercised against PostgreSQL in phase 2.
- Full backend ty passed. New judgment and existing canonical lowerer/capability
  test selection: 97 passed in 9.85s, three dependency deprecation warnings.
  These verify request construction and usage/context isolation, not a real
  model operation or SDK-wire execution.
- Next: actual purpose-owned adapter/normalizer/watchdog operation, SDK-wire and
  cleanup tests, real event persistence/live/client projection tests and generated
  client synchronization. No reviewer request or phase 2 PR yet; no runtime
  judgment activation or material Design delta.

Integrated pre-review checkpoint, 2026-10-18 KST:

- Implemented the purpose-owned operation in `engine/routine_judgment.py`, using
  the ordinary saved selection, official adapters, native terminal proof,
  transient normalization, watchdog and owned cleanup. Invalid completed output
  retains available usage on a failed observation; provider failures and
  cancellation propagate to the future owner. No retry or ordinary Run effect.
- Official SDK-wire fixtures cover OpenAI, ChatGPT OAuth, OpenRouter, xAI,
  xAI OAuth, Anthropic, Gemini and Kimi; the public Boto boundary verifies the
  existing Bedrock Structured-output translation with exactly one output tool
  and no executable tools. Native schema locations and canonical messages are
  checked on the captured requests. This is deterministic fixture evidence,
  not live-provider interoperability evidence.
- Added strict boolean output validation and no-objective/foreign/omitted/duplicate
  candidate tests, incomplete-stream failure, provider-failure/cancellation
  propagation, one-dispatch and client cleanup checks.
- Real PostgreSQL tests upgraded the predecessor to `854782c43687`, appended and
  read observations without a Run, and verified no ordinary Session activity,
  user-input recency or model-input-head changes. This exposed nullable-field
  stripping in the generic serializer; judgment serialization now preserves
  its explicit nullable decision/error/usage slots in storage and public
  projections, with round-trip tests.
- Regenerated public/admin OpenAPI and both Python/TypeScript clients from
  source. The public payload remains the existing JSON projection; generated
  EventKind enums now include the dedicated observation.
- Root validation: full backend `uv run ty check --error-on-warning` passed;
  `uv run ruff check .` passed; `uv run ruff format --check .` passed (2593 files).
  Integrated pytest selection across events, providers, model_text, watchdog,
  context, judgment, transcript repository, PostgreSQL migration/persistence and
  chat context: 1564 passed in 30.10s, three dependency deprecation warnings.
- Forced, uncached TypeScript checks for web/admin/session-core passed (including
  freshly regenerated clients); Session core tests 58 passed, lint and format
  checks passed. No frontend behavior was added.
- Diff is ready for the assigned review. Scheduler, admission, notification and
  product E2E remain future-phase work. No merge, deploy or live credentials.
  Design delta: None.

Review corrections checkpoint, 2026-10-18 KST:

- The assigned reviewer found two P2 contract gaps: compatible custom-call input
  and long results were omitted without executable declarations; Structured
  lowering validated a throwaway ordinary request before the actual output-tool
  capability context existed.
- Root preserved the existing route profile's historical custom replay authority
  separately from executable declarations. Structured Responses lowering also
  reconstructs canonical custom history across old replay schemas, preserving
  complete call input and the same ordinary hard-capped results. Regressions
  compare ordinary/judgment history for OpenAI and ChatGPT OAuth with compatible
  and incompatible old artifacts and long-result tail evidence; judgment still
  declares zero tools.
- Root extracted shared canonical history builders in both lowerers. Structured
  output is assembled before final capability validation and rich-input support
  resolution. Bedrock's translated output tool supplies the actual function-tool
  context. Conditional temperature acceptance/rejection and image-input support
  tests verify this boundary. Ordinary lowering regression coverage is retained.
- Root reran full backend ty, Ruff and formatting (2594 files), and the integrated
  suite: 1570 passed in 37.77s, three dependency deprecation warnings. Generated
  schemas and TypeScript contracts are unchanged by these corrections.
- Phase 1 CI exposed a historical Memory migration fixture using current Session
  ORM against a predecessor schema. Root fixed only that fixture in `ab7834c36`,
  validated the exact PostgreSQL test and hooks, and fast-forwarded PR #2328.
  The same reviewer separately reviewed the fixture correction as clean. Phase 2
  will be rebased onto that foundation before publication.
- Targeted same-reviewer verification closed both P2 findings with no additional
  actionable findings. Root's 1570-test validation is the integration evidence;
  the reviewer remained read-only. Generated Python client template tests also
  passed (16 tests). Design delta: None.
