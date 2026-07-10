---
title: "Per-Prompt Inference Profile Implementation Plan"
created: 2026-07-10
updated: 2026-07-10
tags: [plan, api, backend, chat, database, engine, frontend, testenv, subagent]
---

# Per-Prompt Inference Profile Implementation Plan

## Feature Summary

Implement `docs/azents/design/per-prompt-inference-profile.md` as a nine-PR stack. A run-producing human input explicitly selects an Agent-owned model target and nullable reasoning effort. The server preserves requested intent, resolves the current target policy at each new run, fixes one resolved profile for the run and its automatic retries, and exposes only safe provenance to clients.

The implementation preserves these boundaries:

- clients submit target labels, never provider/model snapshots;
- strict resolution failures are visible and never fall back silently;
- one resolved profile and effective limits remain fixed within an `AgentRun`;
- the first subagent run is the sole exception to normal run-time re-resolution and inherits the parent run snapshot exactly;
- dynamic routing, per-prompt lightweight model selection, and `spawn_agent` profile overrides remain out of scope.

## Stack Prefix

`Per-Prompt Inference Profiles`

## PR Boundaries

| PR | Branch scope | Completion gate |
|---|---|---|
| 1/9 | Design | Approved design and ADR set |
| 2/9 | Implementation plan | Phase boundaries, validation matrix, fixtures, and blockers are explicit |
| 3/9 | Persistence and public API foundations | Migration, repositories, shared profile contracts, event payloads, and backward-readable response foundations |
| 4/9 | FIFO segmentation, request activation, and run activation | Required request fields, OpenAPI and generated clients, minimal profile-aware web wiring, pending-run lifecycle, strict resolution, atomic activation, and typed failures |
| 5/9 | Retry/edit and subagent inheritance | Re-execution intent and precreated inherited child run |
| 6/9 | Compact Composer and provenance UI | Responsive profile selection, restoration, message provenance, and run-based usage |
| 7/9 | E2E/testenv validation and fixes | Deterministic fixtures, automated product matrix, visual evidence, and implementation/spec comparison |
| 8/9 | Spec promotion | Living specs updated and design marked implemented after validation |
| 9/9 | Cleanup | This temporary plan and stale references removed |

Every branch is stacked on the preceding branch. Each implementation PR contains only its phase and focused tests. A public request field is not activated until its runtime semantics are available in the same PR. CI is evaluated after the complete planned stack has been opened.

## PR 3/9 — Persistence and Public API Foundations

### Data and repository changes

- Generate a new Alembic revision; do not modify an executed migration.
- Add typed requested-profile columns and a target/effort consistency constraint to `input_buffers`.
- Add nullable last-used target and effort columns to `agent_sessions`.
- Extend `agent_runs` with:
  - `pending` status;
  - requested target, effort, and source;
  - immutable resolved model-selection snapshot, resolved effort, resolution time, and effective limits;
  - safe typed resolution-failure fields;
  - nullable `parent_agent_run_id`;
  - non-null `created_at` and nullable `started_at`, with existing rows backfilled from prior `started_at`.
- Add `agent_run_input_events` with run/event uniqueness, stable input order, and indexes for run-ordered inputs and latest runs associated with an event.
- Add a partial uniqueness/claim invariant allowing at most one pending run per session.
- Extend domain models, repository mappings, pin/garbage-collection queries, and session-idle queries so `pending` is not treated as terminal.
- Add explicit repository operations for pending creation/claim, activation, typed failure, event association, and latest safe summaries. Do not reuse run creation behavior that auto-cancels an existing running run.

Historical rows and events remain readable with null provenance. Service rules require provenance for every newly created model-producing run.

### API and event contract foundations

- Define shared requested-profile, profile-source, profile-failure, session-profile, and compact safe run-summary types.
- Add typed requested profile to internal InputBuffer and `UserMessagePayload` models, preserving historical event decoding.
- Add backward-readable session last-used profile and compact allowlisted run-summary response foundations. Never return internal resolved JSON.
- Prepare request validators and idempotency comparison helpers for the complete profile without attaching them to run-producing public endpoints yet.
- Keep failed-run retry override-free; reconstruction of original requested intent remains PR 5 scope.
- Do not expose an input selection that the current runtime would ignore. PR 4 activates the required request fields, endpoint validation, OpenAPI, generated clients, and transport wiring together with profile-aware execution.

### Validation

- Migration upgrade/backfill, enum, constraint, and index tests.
- Repository round trips for buffers, sessions, pending runs, associations, activation, and failure.
- Historical event decode without requested profile.
- Shared profile-type and request-helper unit tests without public endpoint activation.
- Safe response-projection allowlist tests.
- Python quality gates for the touched backend workspace.

## PR 4/9 — FIFO Segmentation, Request Activation, and Run Activation

### Public request and generated-client activation

- Add required non-null `inference_profile` to new-session first-message, existing-session run-producing input, and edit requests.
- Keep the combined Composer input field required and nullable: non-model commands send null, while run-producing input requires a profile and rejects null.
- Reject a non-null profile for commands that do not invoke the main model.
- Include the complete requested profile in idempotency payload comparison.
- Keep failed-run retry override-free; it does not accept a replacement profile.
- Expose the backward-readable requested profile, session last-used profile, and compact allowlisted run summary through history, live, and write-response schemas.
- Dump OpenAPI and regenerate the Python and TypeScript public clients only after the request fields and runtime semantics are active together in this PR.
- Update existing web transport call sites with minimal profile-aware wiring: submit the projected session last-used target and effort when present, and use the Agent default only before the session has successfully activated a profile. Interactive selection and full restoration remain PR 6 scope.
- Do not add a legacy request fallback or let the transport reset an existing session to the Agent default.

### Buffer and lifecycle changes

- Preserve requested profile while enqueueing and promoting InputBuffers.
- Split `_next_flush_prefix()` at action barriers and every target/effort mismatch.
- Carry the selected profile and promoted event IDs across the worker boundary.
- Associate exact-profile input that arrives during an active run with that run and reuse its resolved snapshot without routing again.
- Leave different-profile input queued until the active run is terminal, then re-wake the session.
- Create an ordinary requested-only pending run before strict resolution and associate its consumed input events.
- Move first-time run creation/activation out of `AgentEngineAdapter.run()` so the adapter consumes an already activated run rather than creating a duplicate or cancelling it.

### Resolution and activation

- Resolve target labels strictly in worker run preparation against the current Agent selectable targets.
- Keep external runtime/provider adapters label-unaware; they receive only the saved resolved snapshot.
- Apply explicit input, session last-used, then Agent default precedence for internal implicit execution. A failure at an explicit or inherited source does not continue to another source.
- Preserve null effort as visible provider/model Default and validate explicit effort against the selected target.
- Calculate and persist the exact context and auto-compaction limits used by the run.
- In one transaction, persist resolved provenance, set pending to running with `started_at`, and update session last-used profile.
- Invoke tools/providers only after activation commits.
- On resolution failure, atomically mark the pending run failed, leave session last-used unchanged, bypass provider automatic retry, and publish a safe typed failure:
  - `model_target_not_found`;
  - `model_target_resolution_failed`;
  - `reasoning_effort_unsupported`.
- Add recovery for pending or committed-but-not-invoked activation states without re-resolving an already activated run.

### Validation

- Endpoint validation for new-session input, normal input, turn action, command, edit, and retry.
- Idempotency rejection when a reused request ID changes target or effort.
- Session-last-used transport selection with Agent default used only for an uninitialized session.
- OpenAPI and generated-client drift checks plus Python and TypeScript quality gates for touched workspaces.
- Initial and polled FIFO segmentation by exact target and effort.
- Same-profile active continuation versus different-profile queueing.
- Re-resolution for a later run even when requested intent matches a prior run.
- Source precedence, strict missing-target behavior, and absence of first/default-option fallback.
- Unsupported effort and safe failure/log redaction.
- Activation rollback and proof that provider invocation cannot precede commit.
- Session last-used update on activation and preservation on resolution failure.
- Run/event ordering and automatic-retry snapshot stability.
- Pending-run recovery, stop handling, idle detection, and model-file pinning behavior.

## PR 5/9 — Retry, Edit, and Subagent Inheritance

### Re-execution behavior

- Keep provider automatic retry inside the same run with the same resolved snapshot, effort, limits, and run ID.
- Make manual retry create a new pending run from the original requested target and effort with `retry_original` source, then resolve current Agent target configuration.
- Associate one original user event with multiple manual-retry runs without creating a newer human-input Composer intent.
- Load the original typed requested profile for edit, allow changes, and treat the edited replacement as the latest durable human intent.
- Never reuse an old physical snapshot for manual retry or edit.

### Subagent first run

- Retain the concrete parent `TurnContext.run_id` in the Subagent Toolkit.
- Load that exact executing parent run rather than inferring from session history.
- In the child creation transaction, persist child AgentSession, SessionAgent, inherited context, spawn-task InputBuffer/event, and one pending child run.
- Store `parent_agent_run_id`, parent requested intent, `parent_run` source, exact parent resolved snapshot, effective effort, and effective limits.
- Initialize child session last-used profile in the same transaction.
- Publish wake-up only after commit.
- Claim the precreated child run without routing, and make duplicate wake-ups unable to create or claim a second first run.
- Add discoverable recovery/re-wake behavior for commit-success/publish-failure.

### Validation

- Automatic versus manual retry run IDs, requested sources, and resolution behavior.
- Manual retry after target mutation or deletion.
- Edit original-profile initialization, change, cancellation, and replacement intent.
- One event associated with several retry runs.
- Concrete parent-run lookup and rejection of arbitrary source-run selection.
- Exact child snapshot/effort/limits equality and proof that first-child routing is not called.
- Spawn transaction rollback, duplicate claim exclusivity, and pending-child recovery.

## PR 6/9 — Compact Composer and Provenance UI

### State and transport

- Persist message, selected action, target label, and effort as one local draft; profile-only selection is draft state.
- Restore profile in this order:
  1. local unsent draft;
  2. latest durable run-producing human input with a requested profile;
  3. session last-used profile;
  4. Agent default profile.
- Skip null-profile commands and manual retry when finding latest human intent; an edited replacement becomes newer intent.
- During edit, temporarily load the original message profile and restore normal draft state on cancellation.
- Submit explicit profiles through the generated client for new sessions, existing sessions, and edits.

### Composer and provenance

- Replace the flanked input row with a rounded Composer containing an expanding textarea and integrated attachment, Model, conditional effort, and Send/Stop controls.
- Dock the one-line Goal/Todo tab behind the Composer top edge and render attachment/action/edit rows only when present.
- Use separate Model and effort controls on desktop and a combined mobile control with a bottom sheet.
- Keep mobile textarea and placeholder at least 16 CSS pixels, default Composer near 80–84 pixels, exposed Goal/Todo tab near 22 pixels, and interaction targets near 40 pixels. Truncate model labels before increasing height.
- Preserve an explicit effort when supported after target change; otherwise visibly select `Default`. Hide effort selection when the target exposes no selectable effort.
- Render user metadata as `sent time · requested target` and show requested effort, latest associated run state, safe resolved summary, or safe failure on hover/focus/tap.
- Render queued, running, terminal, and failed provenance consistently for durable and live messages.
- Bind context/token usage to the active resolved run or the latest successfully resolved terminal run explicitly associated with the displayed usage snapshot. Before activation, show unknown; never derive observed usage from Composer or Agent default.
- Add localized copy, component/container tests, and colocated stories for meaningful desktop/mobile states.

### Validation

- Draft and restoration precedence, including profile-only draft, commands, edit cancellation, and manual retry.
- Desktop and mobile selection, long labels, Default effort, no-effort targets, and invalid edited effort.
- Provenance keyboard, hover, focus, tap, dismissal, and safe failure interactions.
- Active, associated-terminal, and unknown token usage.
- Composer empty, Goal, Todo, combined Goal/Todo, attachment, action, editing, running, stopped, queued, and failed stories.
- Frontend format, lint, typecheck, build, and focused component/story checks.

## PR 7/9 — E2E/Testenv Validation and Fixes

### Deterministic prerequisites

Extend testenv through supported public/admin APIs with:

- an Agent containing `Fast`, `Quality`, and a non-reasoning target;
- distinguishable physical model identifiers and context limits;
- differing effort capability sets and one intentional incompatibility;
- controllable in-flight delay, one-failure-then-success automatic retry, and provider request journaling;
- target mutation/deletion during a test;
- non-zero subagent capacity and deterministic spawn behavior;
- Goal/Todo session state for Composer layout checks;
- structured access to run IDs, requested/resolved summaries, effective limits, and routing-call evidence.

No required case uses live credentials. Missing deterministic infrastructure is a test setup failure, not a skip.

The current testenv suite is REST/WebSocket pytest and has no committed browser CI harness. Add an automated browser E2E harness and CI path in this phase for Composer restoration, responsive layout, keyboard/touch behavior, screenshots, and computed-style checks. Manual Playwright MCP evidence may supplement but does not replace required automated browser coverage.

### Primary validation matrix

| Scenario | Required assertion and evidence |
|---|---|
| New-session default | Composer default, submitted profile, requested message target, resolved fixture summary |
| Per-prompt target change | Ordered separate runs with distinguishable physical models |
| Effort-only change | Same target and different effort create a separate run |
| Same-profile active continuation | Same run ID and resolved snapshot |
| Different-profile active input | Pending projection remains queued until current run is terminal |
| Local draft reload | Message/action/profile restore together, including profile-only draft |
| Durable latest-intent reload | Latest run-producing human intent wins; command and manual retry are skipped |
| Edit | Original profile loads, changed profile creates a new run, current target resolves |
| Manual retry | Original requested intent, new run ID, current target resolution |
| Automatic retry | Same run ID and resolved snapshot |
| Deleted target | Typed safe failure, previous session profile retained, Edit and Retry available |
| Unsupported effort | Typed failure and editable original state |
| Subagent spawn | Parent run ID and exact snapshot/effort/limits, with no child routing call |
| Context usage | Active or usage-associated resolved run drives model, limits, and percentage |
| Narrow mobile Composer | Default, Goal/Todo, long label, sheet, queued, and failed screenshots meet height constraints |
| Mobile focus | Textarea and placeholder computed size is at least 16px |
| Accessibility | Keyboard/touch open, navigate, select, dismiss, and return focus correctly |

### Evidence and audit

- Record backend, generated-client, frontend, testenv, and browser test commands and results.
- Capture structured run/profile assertions and provider journals as machine-readable evidence.
- Capture desktop/mobile screenshots and traces for layout-sensitive states.
- Validate fixture prerequisites explicitly.
- Produce a strict table comparing implemented behavior with current living specs, including any missing implementation or spec drift.
- Fix discovered defects in this PR or in the responsible earlier phase, then rebase later stack branches with the stacked-PR workflow.
- Optional live-provider smoke tests may skip only when their documented external credential prerequisite is absent; they never replace deterministic tests.

## PR 8/9 — Spec Promotion

Run `/spec-review` after implementation and E2E validation. Update at least the applicable portions of:

- `docs/azents/spec/domain/agent.md` for Agent default-target semantics and session last-used profile;
- `docs/azents/spec/domain/conversation.md` for typed requested intent, run provenance, and run/event associations;
- `docs/azents/spec/flow/agent-execution-loop.md` for FIFO segmentation, pending runs, strict resolution, activation, retry, and subagent inheritance;
- `docs/azents/spec/flow/chat-session-resync.md` for requested-profile and compact run-summary restoration;
- `docs/azents/spec/flow/context-compaction.md` and `session-context-inspector.md` for run-associated effective limits and usage;
- `docs/azents/spec/flow/run-resume.md` if pending claim/recovery changes its contract;
- `docs/azents/spec/flow/test-strategy-e2e-primary.md` if the browser harness becomes a repository-wide test strategy contract.

Set `implemented` on the feature design only after the validated implementation is complete. Do not modify adopted ADRs; record any changed hard-to-reverse decision in a new ADR.

## PR 9/9 — Cleanup

- Remove this temporary implementation plan.
- Remove stale plan references and regenerate the docs index.
- Keep cleanup limited to documentation lifecycle changes; do not mix behavior changes or refactors.

## Dependencies and Rollout

- PR 4 depends on PR 3 persistence and contract types.
- PR 5 depends on PR 4 pending-run lifecycle and event associations.
- PR 6 depends on PR 3 projections and PR 4/5 runtime semantics.
- PR 7 depends on the complete implementation and deterministic fixture controls.
- PR 8 depends on successful PR 7 validation.
- PR 9 depends on spec promotion.

PR 3 lands persistence and backward-readable response foundations without activating run-producing request fields. PR 4 activates the required public request contract, OpenAPI, generated clients, runtime semantics, and minimal web transport together. That transport preserves the projected session last-used profile and uses the Agent default only while the session has no activated profile; no server-side legacy fallback is introduced. Full interactive selection follows in PR 6. Monitor pending-run age/claim failures, failure rates by safe profile code, activation transaction failures, active-profile join mismatches, and child-run recovery. Never emit credentials, decrypted provider configuration, or raw provider failures in provenance, UI, or public logs.

## Known Blockers and Risks

- **Automated browser coverage:** the repository lacks a committed browser E2E CI harness. PR 7 must add one; without it, responsive, accessibility, draft-reload, and focus-zoom guarantees are blocked.
- **Lifecycle ownership:** current first-run creation occurs too late in `AgentEngineAdapter.run()`. Leaving old and new ownership paths active can duplicate or auto-cancel runs.
- **Early input consumption:** current initial promotion deletes buffers before run creation. Event IDs and profile must survive until association and activation are durable.
- **Pending-state audit:** idle checks, stop paths, subagent capacity, pin/GC, projections, and recovery queries must all recognize pending as non-terminal.
- **Null semantics:** `{target, null}` is explicit Default, while `{null, null}` is internal inheritance. Serialization must not collapse these states.
- **Canonical limits:** persist the exact limits used by the run rather than re-deriving them from Agent defaults.
- **Safe projection:** full resolved snapshots remain internal; only purpose-built allowlisted summaries cross the API boundary.

No external service or credential blocker is known. Deterministic provider delay/retry journals, target mutation, distinguishable limits, and subagent routing assertions must exist before PR 7 can pass.

## Test Strategy

Product verification is E2E-first. PRs 3–6 add focused migration, repository, service, API, engine, component, and container tests at the layer where behavior is introduced. PR 7 then validates the integrated user behavior through deterministic REST/WebSocket and automated browser E2E, with structured provenance assertions and visual evidence.

All deterministic unit, type, lint, build, E2E, fixture-prerequisite, and browser checks are required. Missing required prerequisites fail the phase. Live-provider smoke tests are optional and may skip only for a documented absent credential. The full matrix, fixture requirements, evidence format, and failure handling are defined in PR 7 above.
