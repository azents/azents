---
title: "Chat Timeline Reliability Hardening Design"
created: 2026-07-13
updated: 2026-07-13
tags: [architecture, backend, frontend, chat, reliability]
---

# Chat Timeline Reliability Hardening Design

## Overview

This design hardens the complete Chat display pipeline after a source audit found deterministic failures across Worker projection, WebSocket resynchronization, event projection, pagination, and scroll following. It reinforces the existing canonical history/live split from ADR-0047 and the session resync state model from ADR-0053. It does not replace those decisions.

The implementation must preserve durable transcript authority while making every live projection failure recoverable. The browser must either apply a complete REST baseline plus buffered WebSocket observations or release the buffer and continue from observations; it must never remain in an indefinite half-resynchronized state.

## Problem

The current implementation violates several existing invariants.

- Redis WebSocket projection failures can escape into the Agent Run execution path and terminalize an otherwise valid run.
- REST writes can commit durable input, fail during WebSocket publication, skip the Worker wake-up, and return an error for already-applied data.
- A failed REST baseline can leave WebSocket buffering enabled forever.
- Detached history browsing still mutates the visible durable window when new history events arrive.
- Render identity is page-local or session-global where it must be output-specific. Reasoning, provider results, tool pairs, internal agent messages, and durable action results can disappear.
- Pagination advances from rendered rows instead of raw event cursors.
- Bottom-follow hysteresis can override explicit user scroll intent during streaming.
- The public WebSocket path still emits raw durable events in addition to canonical transport actions.

## Goals

- Treat WebSocket and Redis live projection as recoverable observation infrastructure, never as an Agent Run success boundary.
- Preserve committed writes and required Worker wake-ups when UI projection publication fails.
- Make subscribe and health-check acknowledgements represent confirmed current Redis subscription registration.
- Use only canonical Chat transport actions for public durable/live WebSocket delivery.
- Guarantee a finite client resync transaction with success, rollback-to-observations, or reconnect outcomes.
- Keep detached history windows immutable until explicit newer pagination or latest reset.
- Store raw durable event pages independently from rendered rows and derive view models across page boundaries.
- Give live/durable output counterparts stable, turn-safe identities.
- Render provider tool results, live internal-agent messages, and durable terminal action results.
- Preserve immutable requested inference intent on human input rows independently from applied Run provenance.
- Stop follow immediately when explicit user intent leaves the bottom boundary.
- Add deterministic regression coverage for every corrected state transition.

## Non-goals

- Virtualize the Chat timeline.
- Persist model token deltas as durable transcript events.
- Add Service Worker or push-based background delivery.
- Redesign the visual language of message, tool, action, or retry cards.
- Change Agent execution retry policy.
- Modify accepted ADR bodies.
- Preserve the raw durable WebSocket frame as a compatibility surface.

## Existing Decisions

- ADR-0047 keeps durable canonical events and non-durable canonical projections separate and requires canonical WebSocket transport actions.
- ADR-0050 requires history-first durable handoff followed by live counterpart removal and makes live publication best-effort.
- ADR-0053 requires a confirmed session subscription barrier before REST baseline, two timeline states, and detached history isolation.
- Current Living Specs require exact terminal `run_id` correlation and requested inference intent on human input rows.

## Decisions

### D1. Projection failures are non-fatal observations

Every Redis live-store mutation and WebSocket publication invoked from Worker execution is caught at a projection boundary, logged with session/run context, and allowed to converge through REST. `CancelledError` still propagates.

A projection failure cannot:

- prevent provider invocation;
- convert a successful or retryable run into a durable failed run;
- mask terminal persistence;
- prevent session activity cleanup.

Durable DB operations retain their existing failure semantics.

### D2. Essential wake-up is independent from UI publication

After a REST write commits input or a wake-producing goal transition, the API attempts the required broker wake-up independently from WebSocket publication. UI projection publication is best-effort and cannot change the success result of an already committed idempotent write.

Delete-only projection notifications follow the same rule: a committed deletion returns success even if its notification fails.

### D3. Public WebSocket uses canonical actions only

Durable events are delivered as `history_event_appended`. Live events are delivered as `live_event_upserted` and `live_event_removed`. Raw durable `{kind, payload}` frames are removed from the public Chat WebSocket path.

Engine lifecycle observations that remain part of current UI behavior keep explicit typed control frames until they are separately replaced by canonical projections.

### D4. Subscription acknowledgement tracks confirmed Redis registration

The server consumes the Redis `subscribe` confirmation before sending `subscribed`. It records the confirmed subscription generation owned by the WebSocket send loop.

A `subscription_health_check_ack` is sent only when that generation is still current and the send loop remains registered. A reconnect or resubscribe advances the generation; an ack from an earlier generation is invalid.

### D5. Live state is run-correlated without process-local authority

Process-local `_active_run_ids` is not authoritative for clearing shared live state. Terminal operations carry the exact `run_id`, and shared live projection keys or durable current-run validation prevent Run A from clearing Run B.

Active tool projection removal uses deterministic event IDs derived from the call ID and current durable active-call transition, not only an in-memory before-state.

### D6. Client resync is one finite transaction

Initial subscribe, periodic reconcile, browser resume, and latest reset use the same resync transaction.

1. Confirm subscription once.
2. Begin buffering without erasing an already active transaction buffer.
3. Fetch an explicit fresh history/live result associated with the transaction epoch.
4. Apply the baseline only if no newer transaction superseded it.
5. Replay observations and end buffering.

On REST failure, the transaction replays observations and exits buffering before surfacing retry state. On health-check failure, it replays observations and transitions to ticket refresh/reconnect. A stale React Query cache value cannot satisfy a new transaction.

Wire frames are discriminator-validated, session-validated, and replayed with per-frame fault isolation.

### D7. Detached history holds observations instead of mutating its window

Entering `DETACHED_HISTORY_BROWSING` starts a detached observation buffer. New durable/live observations do not mutate the visible window. They only mark a confirmed newer gap. Clicking the chip or reaching the latest durable tail runs latest reset and replaces the detached buffer through a fresh baseline.

Nonterminal live action projections remain hidden. Durable terminal action results remain part of raw history and render in detached mode.

### D8. Raw events and cursors precede view-model projection

The frontend stores raw durable events in ordered pages and tracks server cursors independently from rendered rows. Rendering selectors process the combined event window so tool call/result pairs can cross page boundaries.

- Pagination uses `next_cursor` and `previous_cursor` from the raw API response.
- Empty or control-only pages still advance the cursor.
- The viewport requests older pages until it becomes scrollable or the older boundary is exhausted.
- Durable/live deduplication uses explicit counterpart identity, not a session-global event-kind key.

### D9. Projection covers every user-visible canonical result

- Reasoning identity includes a stable output/turn identity.
- Provider tool results merge by `call_id` and render status, output, and attachments.
- Live `agent_message` projections render using the same collapsed internal-agent row as durable messages.
- Durable `action_execution_result` remains renderable in detached history.
- Assistant partial promotion atomically prefers durable history and cannot show both counterparts.
- Assistant partial cleanup handles every content index represented by the durable boundary.

### D10. Requested intent and applied provenance are separate

Human user/action events expose immutable `requested_inference_profile`. Applied Run provenance remains on the live Run and durable turn marker. The UI never derives missing historical requested intent from the current Agent, Session, Composer, or a newer Run.

Existing historical events without requested intent render provenance as unavailable rather than using an applied-profile fallback.

### D11. Explicit user scroll intent overrides programmatic follow

Follow is active only inside the documented bottom/bounce boundary. Wheel, touch, keyboard, or scrollbar movement that leaves the boundary ends follow immediately, even during a programmatic-scroll guard. Streaming resize can pin only while follow remains active.

The new-message control is keyboard-focusable and uses button semantics. Stored non-follow positions are restored without applying the larger follow-entry threshold.

## API and Data Contract Changes

- `UserMessagePayload` gains nullable `requested_inference_profile` transport data.
- History pagination returns directionally accurate `has_more`, `has_newer`, `next_cursor`, and `previous_cursor` values.
- Generated public clients are regenerated from OpenAPI after schema changes.
- No database migration is required because canonical event payloads are JSON and historical rows remain readable with absent requested intent.

## Error Handling

- Redis live projection failure: structured warning/error observation; durable execution continues.
- WebSocket broadcast failure after REST commit: log and return committed write success.
- Broker wake-up failure: remains an operation failure because execution was not scheduled; idempotency permits safe retry.
- REST baseline failure: replay buffered observations, leave buffering, expose retryable UI state.
- Malformed or wrong-session WebSocket frame: report diagnostic, drop only that frame, continue replay.
- Detached buffer overflow: mark latest reset required and discard detailed held frames; REST remains authoritative.

## Security and Permissions

Existing REST and WebSocket access checks remain unchanged. Session validation on incoming WebSocket frames is an additional client integrity guard, not an authorization mechanism.

## Rollout

The stack is additive until the canonical raw-frame removal phase. Each phase includes regression tests and can be reviewed independently. Descendant branches remain based on their immediate parent. Spec promotion occurs only after validation.

No feature flag is required because all changes restore existing documented behavior. No data backfill is required.

## Test Strategy

### E2E primary matrix

| Scenario | Expected behavior | Fixture requirement |
| --- | --- | --- |
| Redis/WebSocket projection publish failure during Run start and terminal cleanup | Provider execution and durable terminal state remain correct | Deterministic backend fault-injection integration; no external credentials |
| Initial and latest-reset REST failure with concurrent WS observations | Buffer is released and observations remain visible; retry can converge | Browser route interception or deterministic test API failure |
| Detached history receives durable and live events | Visible window is unchanged, chip appears, latest reset converges once | Existing deterministic chat fixture |
| Two reasoning turns with streaming | Both reasoning rows remain distinct and current live reasoning is visible | Deterministic model stream fixture |
| Provider image/tool result | Result status, output, and attachment render after reload and live delivery | Deterministic provider-result fixture; no live provider credentials |
| Tool call/result split at page boundary | One complete tool card renders across older/newer pagination | Seeded transcript with configurable page boundary |
| Live internal-agent message promotion | Live row appears and promotes without flicker or duplication | Existing subagent/message fixture |
| Durable terminal action result in detached history | Terminal card remains visible while live action progress stays hidden | Existing worktree action fixture or seeded action result |
| Streaming while user scrolls upward | Follow stops immediately and no snap-back occurs | Browser wheel/touch simulation |

### Unit and integration coverage

- Worker projection failure injection for update, partial flush, and clear.
- REST commit/broadcast/wake-up ordering.
- Redis subscribe confirmation and health-check generation.
- Run-correlated live cleanup and deterministic active-tool removal.
- Client resync reducer/hook tests for success, REST failure, reconnect, overlap, malformed frames, and stale cache.
- Raw event pagination selector tests, including control-only pages and cross-page tool pairs.
- Projection tests for reasoning, provider result, internal-agent message, action results, and requested inference intent.
- Scroll threshold, user-intent override, saved-position restore, and underfilled viewport tests.

### Fixture and prerequisite policy

All required product coverage must run with deterministic local fixtures. External provider credentials are not required. A live-provider smoke test may be optional and must skip, rather than fail, when credentials are unavailable. Deterministic CI scenarios are mandatory and cannot be skipped.

### Evidence

The validation PR records exact commands, environment, focused results, E2E artifacts where available, and a strict implementation-to-spec comparison. CI is monitored on every current stack head after all PRs are opened.

## Alternatives Considered

### Keep raw durable frames for compatibility

Rejected. ADR-0047 defines canonical transport actions as the final public contract, and compatibility fallback would preserve two competing reducers.

### Fix each rendered symptom without raw event state

Rejected. Page-boundary tool loss, control-only pagination, detached durable action results, and semantic-key collisions share the same root cause: projection happens before page/window reconciliation.

### Reconnect on every resume instead of health-checking subscription

Rejected. ADR-0053 explicitly chooses application-level subscription health checks and REST convergence.

### Make projection publication transactional with durable execution

Rejected. Redis/WebSocket availability must not determine transcript or Agent Run correctness.

## Risks

- Moving the frontend to raw event windows touches a large state surface; phase boundaries and selector tests must keep the change reviewable.
- Redis subscription confirmation behavior depends on redis-py semantics; integration tests must verify the actual library version.
- Historical user events lack requested intent and will show unavailable metadata after the contract correction.
- Run-correlated shared live cleanup must not leave stale keys indefinitely; terminal and TTL tests are required.

## Open Questions

None. The existing ADRs and Living Specs determine the required behavior, and the user authorized autonomous implementation without additional product discussion.
