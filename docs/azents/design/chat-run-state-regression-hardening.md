---
title: "Chat Run State Regression Hardening Design"
created: 2026-07-12
updated: 2026-07-12
tags: [api, backend, chat, engine, frontend, observability, testenv]
document_role: supporting
document_type: supporting-consolidation
migration_source: "docs/azents/design/chat-run-state-regression-hardening.md"
supporting_role: consolidation
---

# Chat Run State Regression Hardening Design

## Summary

This design hardens chat execution state after production regressions where a valid running AgentRun could disappear from the frontend, terminal stream events could disagree with durable run state, Composer profile selection could reset unexpectedly, and historical token usage could lose its model provenance.

The defects are independent and remain separate in implementation and testing. A malformed live snapshot is not a terminal transition. An unexpected `RunComplete` is not the same defect as an idle-looking UI without `RunComplete`. Composer persistence is not run lifecycle state. Turn usage provenance is immutable transcript data rather than browser cache.

## Goals

- Preserve arbitrary reasoning-effort wire values in the frontend without parsing, normalizing, or restricting them to a known enum.
- Keep a valid running Run active when a REST snapshot is malformed, contradictory, or older than already-applied WebSocket state.
- Make the running AgentRun projection authoritative over a contradictory Session idle projection.
- Emit terminal run events only after the corresponding durable run reaches a terminal state.
- Correlate terminal live/control events with `run_id` so stale Run A events cannot clear Run B.
- Preserve the selected Composer profile after successful send.
- Persist the last selected Composer profile independently from the unsent draft.
- Preserve immutable model/profile provenance with every durable `turn_marker` usage snapshot.
- Add deterministic unit, integration, and E2E coverage for each independent regression.

## Non-goals

- Do not change Sequential Input preparation semantics. Preparation failures remain terminal and are not retried.
- Do not restore run-owned model selection. Session current inference state remains the per-turn execution authority.
- Do not infer historical physical model provenance from the current Composer selection or Agent defaults.
- Do not retain legacy compatibility fallbacks for malformed newly produced event contracts.
- Do not redesign the full chat protocol or replace the existing history/live APIs.
- Do not change provider-side reasoning-effort validation. The backend remains authoritative for whether a submitted value is supported.

## Current Failure Modes

### Frontend effort parsing invalidates valid objects

The frontend currently accepts only a finite subset of reasoning-effort strings. A future or already-supported effort value can cause an otherwise valid applied profile or live Run payload to be discarded. REST snapshot replacement then interprets the parse failure as Run absence and clears active UI state.

### REST replacement can erase newer or valid live state

WebSocket parse failure preserves the existing state, but REST baseline and write snapshots replace the managed live state. A malformed `run`, a contradictory `session_run_state`, or a stale response can therefore make the UI look idle while the backend continues executing.

### Terminal event publication is not bound to durable terminal state

`SessionRunnerErrorReporter.report_unhandled()` can publish `RunComplete` while its caller reports that no terminal event was observed and a running AgentRun may remain active. Several terminal control events also omit `run_id`, so a delayed event from a previous run can clear the current run.

### Composer draft and durable selection have mixed lifecycles

A successful send clears the draft and resets the selected profile to the normalized default. The existing localStorage entry is an unsent draft, not a durable last-selected profile. Deleting that draft also deletes the only browser-side memory of the user's selection.

### Usage outlives live Run provenance

`turn_marker` persists usage and `run_id`, but the displayed model/profile is recovered only from a matching current live Run. After terminal cleanup, reload, or parser failure, the same durable usage becomes unattributed even though the model step already had a Session inference snapshot.

## Decisions

### 1. Treat reasoning effort as an opaque frontend string

Frontend wire/state types use `string | null` for reasoning effort. The public request/response OpenAPI field is also a nullable string rather than a generated closed enum. Before typed InputBuffer or Session persistence, backend request handling converts supported strings to the canonical `ModelReasoningEffort` enum and rejects unsupported strings without writing state; preparation revalidates target capability authoritatively. Runtime frontend mapping verifies only that a non-null value is a string; it does not enumerate, normalize, downgrade, or reject values.

The raw value must survive:

- REST history and live snapshot mapping;
- WebSocket live updates;
- Composer state;
- unsent draft persistence;
- last-selected profile persistence;
- user-message and usage-provenance rendering.

UI capability lists may still present backend-advertised choices. They do not redefine the wire contract. Submission errors for unsupported values come from the backend.

### 2. Distinguish absent, invalid, and present Run snapshots

Run snapshot mapping returns an explicit result:

- `present`: a valid Run projection was decoded;
- `absent`: the server explicitly returned `run: null`;
- `invalid`: a non-null Run projection could not be decoded.

An invalid snapshot never clears an existing Run. It records an observable parse failure and preserves the last valid state until an explicit correlated clear or a valid replacement arrives.

### 3. Use frontend observation generations for live-state ordering

The frontend owns a monotonic observation generation for each mounted session. Applying a valid WebSocket live-state event increments the generation. Every REST live or write request records the generation and request epoch at dispatch time.

- Subscription/reconcile baselines continue to buffer WebSocket events, apply the REST baseline, and then replay the buffered events. Only the newest baseline request epoch may commit.
- A write response may replace the compound managed live snapshot only when no newer WebSocket live-state observation has advanced the generation since the request began.
- An older or superseded REST response is ignored for Run, partial history, input buffers, Todo, and action-execution replacement together; its non-snapshot mutation result may still be processed.

This order contract is local to the mounted chat session and does not add a distributed server revision. It prevents delayed write responses and overlapping periodic reconciles from moving state backward while preserving the existing subscribe-ack buffering boundary.

### 4. Make a valid running Run authoritative

When `/live.run` contains a valid Run with active status, the effective frontend and API `session_run_state` is running even if the persisted Session projection says idle. The backend logs the contradiction with session and run identifiers for diagnosis.

An explicit correlated terminal clear remains authoritative after the durable terminal transition.

### 5. Bind terminal control events to durable run identity

`RunComplete`, `RunStopped`, and `live_run_cleared` include `run_id`. Frontend terminal handling clears managed state only when the event `run_id` matches the currently active Run. A terminal event for an older Run is ignored for current-state clearing.

The event contract follows [terminal-260712/ADR](../adr/terminal-260712-terminal-events.md).

### 6. Publish `RunComplete` only from terminal finalization

The session-level unhandled error reporter publishes a user-safe `system_error` observation but does not independently publish `RunComplete`.

- Before a concrete Run exists, the failure remains a message-processing failure with no run terminal event.
- After a Run exists, the error is routed through the existing failed-run finalization boundary, which first persists terminal run state and terminal transcript output, then publishes `RunComplete(run_id=...)`.
- Preparation failures retain their current terminal/no-retry policy and finalize through their established terminal boundary.

### 7. Separate draft persistence from selected-profile persistence

The unsent draft key continues to own message text, selected action, attachments where applicable, and the draft profile. A new agent/session-scoped last-selected-profile key owns only the most recently selected target label and raw nullable effort.

Restoration precedence becomes:

1. unsent local draft profile;
2. stored last-selected profile when its target still exists;
3. newest durable or pending applied human profile;
4. Session current profile;
5. Agent default.

A deleted target invalidates only the stored selection and falls through to the next source. Successful send clears message/action draft data but preserves the current selection and updates the last-selected profile.

### 8. Persist immutable turn usage provenance

`TurnMarkerPayload` stores an immutable applied inference snapshot beside usage:

- `run_id`;
- model target label;
- raw nullable reasoning effort;
- nullable `model_display_name`, using the same user-facing allowlisted field already exposed by applied inference profiles;
- effective context window and compaction threshold when available.

This snapshot describes the model call that produced the usage marker. It does not mutate later and does not join transcript events back to current AgentRun state.

This extends the run-owned provenance policy only for immutable per-turn usage facts, as recorded in [persist-260712/ADR](../adr/persist-260712-persist-turn-usage-inference-provenance.md).

## API and Data Changes

- Add `run_id` to terminal engine/control events and WebSocket payloads.
- Widen public reasoning-effort request/response fields to nullable strings while retaining authoritative backend support validation.
- Extend `TurnMarkerPayload` and public canonical event schema with nullable applied inference provenance.
- Regenerate public OpenAPI and generated Python/TypeScript clients.
- No database migration is required for the turn-marker payload extension because event payloads are JSONB and historical payload fields remain nullable.

## Error Handling and Observability

- Invalid non-null Run snapshots are reported through structured frontend observability and preserve the last valid Run.
- Backend `/live` projection logs active-Run/Session-idle contradictions with `session_id`, `run_id`, persisted session state, and run status.
- Stale terminal events and stale live revisions are ignored without mutating current state; debug telemetry may count them.
- Unknown reasoning-effort strings are not errors in the frontend.

## Rollout

1. Add frontend opaque effort handling and invalid/absent snapshot distinction.
2. Add live revisions and running-Run precedence.
3. Add run-correlated terminal events and remove nonterminal `RunComplete` publication.
4. Separate Composer last-selection persistence from drafts.
5. Add immutable turn usage provenance and regenerate clients.
6. Run deterministic E2E validation and promote current specs.

Backend and frontend contract changes land in the same stack before deployment. Generated clients are regenerated from OpenAPI rather than edited manually.

## Test Strategy

Product behavior verification is E2E-first, with focused unit and integration tests for ordering and terminal contracts.

### E2E primary matrix

| Scenario | Expected evidence |
|---|---|
| Expanded supported effort value | `none`, `minimal`, `xhigh`, or `max` survives public write, live/history mapping, reload, Composer persistence, and visible metadata. |
| Unknown/future effort read compatibility | An injected unknown response value survives frontend decoding, persistence, and rendering; submitting it is passed unchanged to the backend and may be rejected authoritatively without a client-side rewrite. |
| Client-tool boundary | Running/pending UI and Stop control remain visible between tool result and the next model call. |
| Contradictory live snapshot | Valid running Run wins over Session idle and produces a backend diagnostic. |
| Stale REST response | Newer WebSocket Run state remains active after an older write or reconcile response arrives. |
| Malformed non-null Run | Existing valid Run remains visible; explicit `run: null` clears only from the newest applicable REST request epoch. |
| Stale terminal event | Run A terminal event does not clear active Run B. |
| Unhandled pre-run error | User-safe error is emitted without `RunComplete`. |
| Unhandled active-run error | Durable failed terminal state exists before correlated `RunComplete`. |
| Successful send | Text/action draft clears while Model/effort selection remains unchanged. |
| Reload after send | Last-selected profile restores without an unsent draft. |
| Deleted selected target | Stored selection is discarded and restoration falls through deterministically. |
| Historical usage reload | Turn usage retains the model target, raw effort, model display, and effective limits after live Run cleanup. |

### Unit and integration coverage

- Opaque reasoning-effort decoders accept arbitrary strings and reject only non-string values.
- Snapshot decoder distinguishes explicit absence from invalid presence.
- Observation generation and request-epoch reducers reject stale or superseded REST replacements.
- Active Run projection forces effective running state.
- Every terminal control event serializes `run_id`.
- Frontend clearing requires matching `run_id`.
- Session error reporter cannot emit `RunComplete` directly.
- Failed-run finalization persists terminal state before publication.
- Composer draft and last-selection keys have independent lifecycle tests.
- Turn-marker serialization/deserialization remains compatible with historical payloads lacking provenance.

### Fixture and prerequisite requirements

Use the existing deterministic model-listing and execution fixtures. Extend deterministic test support only where needed to:

- emit an arbitrary future effort string in projection fixtures;
- pause at a client-tool boundary;
- deliver controlled stale REST/WS ordering;
- create two consecutive Runs and delay Run A's terminal event.

No external credentials are required. Missing deterministic fixture support is a required-test failure, not a skip.

### Evidence and CI policy

Required evidence includes focused backend/frontend test output, deterministic public E2E assertions, and a browser trace or screenshot showing the running control state through a client-tool boundary. All deterministic tests run in required CI. Optional live-provider checks do not replace deterministic coverage.

## Spec Impact Candidates

- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/chat-session-resync.md`
- `docs/azents/spec/flow/context-260530-context-inspector.md`

## Alternatives Considered

### Expand the frontend effort enum

Rejected. A finite client enum recreates the same compatibility failure when the backend or provider adds another value.

### Treat any malformed Run as absent

Rejected. Parse failure is not evidence of a terminal transition and can hide a still-running backend Run.

### Add a distributed live revision without one projection owner

Rejected. Current live snapshots assemble PostgreSQL and Redis state across multiple publishers. A server revision would require a new atomic projection owner. Frontend observation generations solve the identified stale-response race within the existing subscribe/replay boundary.

### Keep terminal events uncorrelated

Rejected. Session-level event ordering alone cannot prevent delayed Run A cleanup from clearing Run B.

### Cache usage provenance only in the browser

Rejected. Browser cache does not survive a different device, storage clear, or authoritative history reload.

### Join historical usage to AgentRun on every read

Rejected. The usage marker already represents an immutable model step. Persisting its snapshot avoids mutable joins and preserves append-only transcript behavior.
