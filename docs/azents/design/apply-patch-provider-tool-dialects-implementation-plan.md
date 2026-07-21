---
title: "Apply-patch provider tool dialects implementation plan"
created: 2026-07-21
updated: 2026-07-21
tags: [architecture, backend, engine, frontend, llm, testing]
---

# Apply-patch provider tool dialects implementation plan

## Purpose

This document is the reviewable delivery plan for
[ADR-0179: Select Provider-Specific Tool Dialects for Apply-Patch](../adr/0179-apply-patch-provider-tool-dialects.md)
and the accompanying
[provider tool dialect design](./apply-patch-provider-tool-dialects.md).

It turns the approved design into independently reviewable, compile-safe pull requests.
The implementation changes only model/provider-to-Engine transport. The Runtime Runner remains the
sole owner of strict V4A parsing, path confinement, preflight, staging, commit ordering,
cancellation settlement, and typed operation results.

## Delivery invariants

Every phase preserves these invariants:

- One logical `apply_patch` tool has one selected wire dialect for one prepared model request.
- A selected call never retries through another dialect after provider failure, malformed input,
  cancellation, or ambiguous completion.
- A durable call has exactly one execution identity based on its existing call ID; dialect is not an
  additional execution key.
- New calls and results persist an explicit closed `wire_dialect`; persistent records that predate
  this feature interpret only a missing dialect as `json_function` at a database read boundary.
- Explicit null, malformed, unknown, or mismatched dialect values fail closed.
- Raw tool input, patch text, source text, replacement text, and path values never enter logs,
  metrics labels, exception text, telemetry, or new fixtures.
- No production request can select `plaintext_custom` until the whole fleet can deserialize,
  execute, recover, lower, project, compact, export, and render its lifecycle.
- Once production custom records exist, later rollback disables new selection only. It never removes
  custom lifecycle readers or relabels existing records.

## Stack and merge order

The stack uses eight small PRs. Each PR is based on its predecessor and should remain mergeable in
this order. CI failures are fixed in the owning PR before the next dependency relies on it.

| PR | Title | Base | Scope | Production custom selection |
| --- | --- | --- | --- | --- |
| 1 | `apply-patch tool dialects [1/8]: Design` | `main` | ADR-0179 and implementable architecture | impossible |
| 2 | `apply-patch tool dialects [2/8]: Implementation plan` | PR 1 | this execution plan and acceptance matrix | impossible |
| 3 | `apply-patch tool dialects [3/8]: Canonical dialect compatibility` | PR 2 | durable models, readers, lifecycle propagation | impossible |
| 4 | `apply-patch tool dialects [4/8]: Dual-dialect engine lifecycle` | PR 3 | selected variants, normalizers, lowering, continuation | impossible |
| 5 | `apply-patch tool dialects [5/8]: Custom apply-patch transport` | PR 4 | envelope, OpenAI profile policy, UI, deterministic E2E | disabled by default |
| 6 | `apply-patch tool dialects [6/8]: Validation hardening` | PR 5 | failure matrices, recovery, privacy, cross-provider checks | disabled by default |
| 7 | `apply-patch tool dialects [7/8]: Living spec promotion` | PR 6 | current-behavior specs and implementation audit | disabled by default |
| 8 | `apply-patch tool dialects [8/8]: Cleanup and release gate` | PR 7 | dead-code removal, deployment/release checklist, final verification | disabled pending approval |

PR 8 does not turn on a production cohort. Controlled enablement is an operational decision after
all deployed consumers meet the permanent reader floor and reviewed evidence exists for an exact
provider/model profile.

## PR 3 — Canonical dialect compatibility

### Scope

Introduce the closed canonical `ClientToolWireDialect` discriminator with exactly:

- `json_function`
- `plaintext_custom`

Add it to canonical client calls, results, and active calls. New in-process writers require the
field explicitly. Persistent database JSON readers upgrade only absent legacy fields to
`json_function` before validation.

Update every current function-call lifecycle producer that constructs a result synthetically so that
the result copies the originating call dialect. This includes normal execution, handler failures,
materialization failures, unavailable-tool outcomes, User Stop, recovery, cancellation, and final
settlement. A result dialect cannot be caller-selected independently.

### Required boundaries

- Event transcript and active-call database readers apply the legacy upgrader before Pydantic
  validation.
- Legacy message projections retain the discriminator instead of erasing it while creating a
  function-only compatibility object.
- Live state, WebSocket projections, REST history, worker recovery, and frontend durable-event types
  retain the field even while all produced calls remain `json_function`.
- Pair finalization validates both call ID and dialect. A mismatch is corruption and must not be
  repaired by current route capabilities or provider artifacts.

### Exclusions

- No provider custom declaration, custom stream branch, plaintext parsing, route profile, or
  production rollout configuration.
- No semantic change to an existing JSON function call.

### Acceptance criteria

- A newly generated ordinary call and every synthetic result explicitly stores
  `json_function`.
- A stored legacy event or active call that omits the field reads as `json_function`.
- Explicit null, unknown, malformed, and call/result-mismatched values fail closed.
- Restart, User Stop, live state, history, and legacy message projections preserve the dialect.
- Existing function-only engine behavior and snapshots remain unchanged except for the additive
  explicit discriminator.

## PR 4 — Dual-dialect engine lifecycle

### Scope

Generalize the logical client-tool representation without changing the Runtime tool contract.
A prepared catalog selects one provider-facing variant per logical tool before model dispatch. The
existing JSON function variant stays behaviorally equivalent. The new plaintext custom variant is
available only to dormant internal test paths until PR 5 introduces its positive selection policy.

Extend the provider event pipeline to represent custom input independently from the old
`function_call_delta` UI event. Completed custom inputs are admitted only after verified completion;
partial input is private bounded transport state.

### Required boundaries

- Provider-neutral logical tool and selected-variant types distinguish declaration format,
  input decoder, call dialect, and output lowering.
- JSON function declarations and parsing use the existing behavior through an explicit
  `json_function` variant rather than an implicit `FunctionTool` assumption.
- OpenAI Responses normalization recognizes typed custom calls and custom-input stream lifecycle.
  The shared dictionary normalizer recognizes safe custom shapes for fixtures and future routes.
- The normalizer verifies ordered delta, done, and completed-item input agreement when more than one
  representation is supplied. Incomplete or oversized custom input creates no durable call and
  invokes no handler.
- Lowering emits matching call/result item types for each dialect. Orphan cleanup is pair- and
  dialect-aware.
- Same-run continuation preserves exact selected dialect and original call ID. A pending custom
  continuation cannot be converted to text or relabeled for an incompatible route.
- Completed historical pairs may use only a bounded, explicitly non-executable readable projection
  where a later compatible lowerer cannot encode their stored dialect.
- Hooks, compaction, context inspection, and exports branch on dialect and never assume custom input
  is JSON.

### Exclusions

- No `apply_patch` custom envelope declaration or provider/model allowlist.
- No route is authorized to select the custom variant outside deterministic internal tests.

### Acceptance criteria

- The complete function lifecycle continues to serialize, lower, continue, recover, and render as
  `json_function`.
- A fixture-backed custom call survives canonical normalization, result persistence, exact matching
  custom output lowering, and same-route continuation without parsing or transforming input.
- Invalid, incomplete, oversized, undeclared, or mismatched custom calls invoke no client handler.
- Custom deltas are never published as the function-delta stream and never render a live patch
  preview.
- Historical fallback cannot create an executable active call.

## PR 5 — Custom apply-patch transport, policy, UI, and deterministic E2E

### Scope

Add `apply_patch`'s plaintext envelope parser and a generic OpenAI `type=custom` declaration. Add
code-owned semantic and route-transport profile selection so only an exact reviewed official OpenAI
API-key Responses route may select the custom variant. All other routes remain JSON function fallback
only when both V4A semantic eligibility and verified function transport are true; otherwise
`apply_patch` is omitted.

Add the frontend adapter for dialect-aware existing tool activity. The JSON parser continues to
validate the current argument shape. The custom parser validates only the exact bounded header and
passes the unmodified body to the existing V4A preview adapter. Any invalid presentation input falls
back to the Generic card.

### Required boundaries

- Custom input begins with one exact ASCII base-path header followed immediately by V4A content.
  Parsing rejects malformed or oversized envelopes without displaying or logging their contents.
- The parser extracts an absolute Runtime path without trimming, normalization, line translation,
  JSON round-trip, or V4A reconstruction. The Runner receives exactly the body substring after the
  first LF and remains authoritative for all V4A/file validation.
- Custom capability requires provider identity, API-key route, native Responses adapter, canonical
  official endpoint, reviewed exact model profile, semantic profile, and a disable-only gate. Any
  missing or inconsistent evidence is denial.
- ChatGPT OAuth, custom endpoints, Azure, OpenRouter, gateways, aliases, route pools, and unknown
  models cannot select custom in this phase.
- The positive rule is code-owned. Configuration can only reduce exposure and cannot admit an
  unreviewed route.
- Selection occurs before request construction and freezes in the prepared catalog. It has no
  custom-to-function retry path.
- E2E fixtures exercise the public API, worker, engine, Runtime Control, runtime provider, and
  Runner with a disposable Runtime root. Fixtures and asserted logs contain only synthetic safe
  content and redacted marker checks.

### Acceptance criteria

- Official reviewed route + enabled test gate exposes one plaintext custom declaration under the
  logical `apply_patch` name.
- JSON function fallback is selected only by a preselected verified fallback profile; function
  support alone never grants V4A eligibility.
- A valid custom call invokes Runner exactly once and preserves the final workspace manifest.
- Malformed header, incomplete stream, oversized input, undeclared dialect, and cancellation cases
  meet their zero-or-one Runner invocation bounds.
- Live/history projection and the web card preserve the dialect and display valid custom activity
  without analytics or error-report body capture.

## PR 6 — Validation hardening

### Scope

Close lifecycle gaps discovered by the implementation test matrix. This phase owns cross-provider
history lowering, restart/recovery, User Stop, compaction, redaction, declaration budgets, Tool
Search, and provider-output edge cases that require test-driven adjustment after PRs 3–5 are
integrated.

### Required checks

- OpenAI HTTP and WebSocket event fixtures cover deltas, done, completed item, response completion,
  failure, incomplete, and EOF.
- Continuation accepts exact matching custom input/output pairs only; mismatched native item types,
  order, or call IDs disable continuation rather than repairing history.
- Every cancellation and recovery synthetic result copies the existing dialect.
- Request profile changes on a later model boundary cannot reinterpret durable calls.
- Compaction, exports, trace-safe diagnostics, UI state, and telemetry tests prove raw custom input
  is not emitted by new instrumentation.
- Tool Search and declaration budget calculations count selected declarations correctly while
  retaining current provider-specific function constraints.

### Acceptance criteria

- Required deterministic E2E scenarios pass without live credentials.
- Optional live checks skip only when credentials or an approved exact profile are absent; when
  prerequisites are supplied, a provider or assertion failure is a test failure.
- No test fixture, captured log assertion, metric label, or error value requires raw input content.

## PR 7 — Living spec promotion

### Scope

Run the dedicated spec review after the behavior is stable. Promote implemented current behavior to
the relevant living specs and create an implementation audit that maps ADR-0179 decisions to code
and test evidence. Do not edit ADR-0179.

### Expected spec updates

- `spec/flow/agent-execution-loop.md`: selected dialect, provider normalization, admission,
  execution, continuation, recovery, and compatibility floor.
- `spec/domain/toolkit.md`: one logical tool, selected provider variants, catalog freezing, Tool
  Search, and declaration budgeting.
- `spec/domain/conversation.md`: durable/live dialect fields and bounded historical projection.
- `spec/flow/context-compaction.md`: dialect-aware rendering and non-executable custom summaries.
- `spec/flow/run-resume.md`: dialect-preserving terminal settlement and recovery.
- `spec/flow/agent-runtime-control.md`: confirm no change to the Runner-owned V4A execution
  boundary.

### Acceptance criteria

- Each changed current-behavior spec has a current `last_verified_at`, incremented version, and
  accurate `code_paths` coverage.
- The audit explicitly identifies test evidence for custom and JSON function paths and documents
  any remaining operational enablement prerequisite.

## PR 8 — Cleanup and release gate

### Scope

Remove temporary migration scaffolding that no longer serves readers, make safety boundaries
explicit in tested code, and document the deployment barrier that must be met before an operator can
authorize a bounded custom cohort. This PR remains selection-disabled by default.

### Release-gate checklist

- All service and worker binaries that can consume delayed, recovered, compacted, exported, live,
  or historical event data meet the full dual-dialect reader floor.
- Old leases, delayed tasks, retries, and dead-letter records are drained or fenced to upgraded
  consumers.
- Exact official route/model profile evidence is recorded outside source input data.
- The global/profile kill switch defaults to disabled and only reduces exposure.
- Dashboard metrics include safe declaration, fallback, failure-category, continuation, and
  cancellation counts without path, call ID, input, or output labels.
- The bounded enablement procedure is reviewed independently. Enabling a cohort is not part of this
  source change or CI acceptance.

### Acceptance criteria

- The final test matrix and project quality checks are green for the complete stack.
- An operator can disable new custom selection without affecting existing custom lifecycle handling.
- No obsolete function-only assumption remains in production code for a client-tool call/result
  boundary.

## E2E-first acceptance matrix

| Scenario | Required route/profile | Expected outcome |
| --- | --- | --- |
| Existing JSON apply-patch | existing eligible function route | unchanged function call and Runner behavior |
| Reviewed official custom route | semantic + exact custom profile + test gate | one custom declaration and one Runner execution |
| Unknown official model | semantic possibly eligible, custom unknown | function fallback only if a verified function profile exists |
| Custom base URL or OAuth | any semantic result | never custom; fallback only if independently verified |
| Non-OpenAI function-capable model | function transport only | no `apply_patch` without V4A semantic approval |
| Incomplete custom stream | reviewed custom fixture | no durable call and zero Runner execution |
| Malformed envelope | admitted custom call | one failed result and zero Runner execution |
| Oversized custom input | reviewed custom fixture | no durable call and zero Runner execution |
| Undeclared custom dialect | function-only prepared catalog | one failed result and zero handler execution |
| Restart after custom admission | reviewed custom fixture | at-most-once execution and copied result dialect |
| User Stop boundary | reviewed custom fixture | existing settlement semantics with preserved dialect |
| Incompatible later route | completed historical custom pair | bounded non-executable history; no active call |
| Legacy durable state | event/active JSON omits dialect | explicit `json_function` interpretation at read |

## Validation policy

Each code PR runs its directly affected unit and integration coverage, Python formatting/lint/type
checks, and applicable frontend checks. The final validation phase runs the deterministic E2E matrix,
Runtime Control and Runner regressions, backend suites, frontend format/lint/type/build, pre-commit,
and documentation validation.

The stack is not considered complete until its required GitHub CI checks are green. CI failures are
fixed on the owning stacked branch with normal forward commits. No branch is force-pushed, and no PR
is merged without explicit user approval.

## Risks and responses

| Risk | Response |
| --- | --- |
| An additive dialect field reaches an old reader | Keep custom selection impossible until the full-fleet reader barrier is met. |
| A generic abstraction silently changes JSON behavior | Preserve an explicit JSON variant and regression-test current declarations, parsing, and outputs. |
| A provider stream produces conflicting custom representations | Treat the call as incomplete/invalid and never execute it. |
| A later route cannot represent custom history | Preserve durable events and use only a bounded non-executable historical projection after a successful later model boundary. |
| UI parsing exposes raw input through telemetry | Keep parsing local to presentation and add redaction/analytics regression tests. |
| Route rules accidentally broaden through aliases or compatibility APIs | Use exact code-owned positive profiles and fail closed on unresolved routing. |
| Large cross-cutting change produces review-blindness | Keep each PR limited to one lifecycle boundary and require its own test evidence. |
