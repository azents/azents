---
title: "Slack Channel Work Presence and Tracker Parity Design"
created: 2026-08-29
updated: 2026-08-29
implemented: 2026-08-29
tags: [slack, external-channel, activity-tracker, backend, testenv]
document_role: primary
document_type: design
snapshot_id: slack-260829
---

# slack-260829/DESIGN: Slack Channel Work Presence and Tracker Parity

- Snapshot: `slack-260829`
- Document reference: `slack-260829/DESIGN`
- Requirements:
  [`slack-260829/REQ`](../requirements/slack-260829-work-presence-parity.md)
- Decisions:
  [`slack-260829/ADR`](../adr/slack-260829-work-presence-parity.md)

## Current Behavior and Gaps

Slack Work is always Tracker-visible because both ingress visibility classifiers
special-case the Slack provider. No durable Work field retains the Slack message
coordinate needed for channel-based loading, and no Gateway manager projects Slack
Work presence.

Slack progress uses one retained `task_card` or `plan` message with only a
`View session` action. An eligible explicit invocation on an existing Binding creates
a separate settings-only control. Final reply delivery gates Tracker deletion.

The generated Slack manifest describes a conventional Bot App and does not declare
the Agent feature. The pinned Slack SDK predates the Agent Session methods.

Provider-neutral response-mode and Binding precedence are already shared. The audit
must verify that no additional Slack-only admission or reply-target drift exists
after removing the settings-only side effect and provider-specific Tracker visibility.

## Requirement Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `slack-260829/REQ-1` | M1, M2, M3, M4 |
| `slack-260829/REQ-2` | M1, M5 |
| `slack-260829/REQ-3` | M5, M6 |
| `slack-260829/REQ-4` | M2, M3, M5 |
| `slack-260829/REQ-5` | M1, M2, M5, M7 |
| `slack-260829/REQ-6` | M4 |
| `slack-260829/REQ-7` | M7 |

## Architecture and Source of Truth

Canonical `ChannelWorkState` remains the only authority for whether Work is active,
whether its Tracker is hidden or visible, and what desired progress must be rendered.
Slack presence is a derived provider projection.

A dedicated `SlackWorkPresenceManager` runs beside the existing Slack Socket,
Discord Gateway, and ingress-recovery managers in the External Channel Gateway. It
claims and renews one presence lease per Slack connection. The lease is independent
of HTTP or Socket ingress transport because both transport modes require the same
outbound status reconciliation.

For each owned connection the manager:

1. decrypts the current Bot credential;
2. periodically loads connected Slack Bindings and their current/latest Work state;
3. derives one desired presence state per Binding;
4. compares it with process-local observed state;
5. invokes the target-appropriate public Slack SDK method;
6. renews channel loading before its two-minute provider expiry; and
7. clears observed states no longer backed by active Work.

Provider results never mutate Work or connection health. Lease loss, configuration
change, disconnect, credential replacement, and shutdown stop the owned loop.

## Work State and Presence Coordinates

Channel Work Toolkit State advances to schema version 3 and adds two required nullable
Slack presentation fields:

- `slack_presence_thread_ts`: exact provider message/thread timestamp used for
  presence; and
- `slack_presence_initiator_user_id`: initiating Slack participant required when the
  thread API creates its Agent Session.

The data migration preserves every existing schema-version-2 Work state by adding
both fields as null and advancing the Toolkit State record and payload schema version.

For a new Slack Work cycle:

- parent-channel Resource: the first admitted trigger message timestamp becomes the
  presence anchor;
- thread Resource: the retained root `thread_ts` becomes the presence anchor; and
- the first triggering human becomes the initiator.

Provisioning may create the Work before the first queued trigger is accepted. A later
acceptance fills missing Slack presence coordinates in the same active cycle without
changing visibility or Work identity. Later messages in the same active cycle do not
move its presence anchor.

Finished Work retains its coordinates so a new Gateway owner can issue one idle/clear
projection after a process failure. A replacement cycle receives new coordinates.

## Channel Presence Projection

Parent-channel Work uses the public SDK
`assistant_threads_setStatus(channel_id, thread_ts, status, ...)`.

- Active Work sends a concise localized checking or Work title.
- The manager refreshes unchanged active status before Slack's two-minute expiry.
- Finished or removed Work sends an empty status.
- The exact trigger timestamp is never used as Resource, Binding, Session, history,
  or reply-target authority.

## Thread Presence Projection

Thread Work uses the public SDK
`agents_sessions_setStatus(channel_id, thread_ts, status, initiator_user_id, ...)`.

- Active Work sends `processing`.
- Finished Work sends `active`.
- Binding termination is satisfied by removal of active presence; this snapshot does
  not add native Stop or App Home execution behavior.
- `feature_disabled`, authorization, scope, and other confirmed rejections are
  sanitized presence failures and receive no compatibility fallback.

The SDK is upgraded to a version that exposes the Agent Session methods.

## Agent Installation Contract

Generated Slack App manifests add:

- `features.agent_view.agent_description`; and
- a read-only App Home Messages tab, with no Azents `message.im` subscription.

The required Bot scopes include `assistant:write` in addition to the existing
`chat:write` and conversation scopes. Connection validation identifies missing
required scopes and instructs the operator to update and reinstall the App.

Bot-token validation cannot prove Workspace-level Agent feature availability without
mutating a real thread. Runtime `feature_disabled` therefore remains a sanitized
presence failure. No App configuration token is introduced.

## Tracker Parity

Both Slack visibility classifiers stop special-casing the provider. They return
visible only for explicit invocation and hidden for ordinary all-messages admission.

The existing canonical `continue` promotion from the stacked
`tracker-260829` snapshot applies provider-neutrally and creates one Slack Plan from
the complete snapshot when unfinished Todos first appear.

Slack progress rendering appends one action row containing:

- `View session`; and
- signed Binding-scoped `Conversation settings` for conversational Work.

Scheduled Task progress retains its current action set and does not receive the
settings action.

The existing ingress branch that creates a settings-only control for an eligible
Slack invocation is removed, together with its payload/renderer path and dedicated
tests. Explicit invocation still promotes hidden Work and claims the normal Tracker
create.

Final reply ordering, projection compare-and-set, confirmed-missing replacement, and
delete behavior remain unchanged.

## Message Routing Audit

The audit verifies and retains:

- explicit invocation triggers either response mode;
- ordinary input requires an existing `all_messages` Binding;
- exact connected thread Binding resolves before parent participation;
- connected-App and unsupported message mutations remain non-triggering;
- mailbox history retains the exact physical source and prompt-role boundaries; and
- final replies use the Resource's current parent-channel or exact-thread target.

Provider-specific Slack parent fan-in and Thread Resource construction remain
authoritative. Any failing parity test is corrected without changing those mappings.

## Security and Permissions

- Presence calls use the current connection's encrypted Bot token only after a valid
  presence lease is claimed.
- The manager revalidates connection status, provider, configuration generation, and
  lease ownership before renewal.
- Work presence payloads contain only provider coordinates, bounded status text,
  initiator identity, and current Agent presentation.
- Conversation settings actions retain the existing signed Binding scope and callback
  authorization.
- No App configuration token, raw callback, message content, or provider response body
  is persisted.

## Failure, Retry, Recovery, and Rollout

- Immediate ingress, Work, Tracker, and reply transactions do not wait for presence.
- Presence failure is logged with sanitized provider/error classification and retried
  only on a later owned reconciliation.
- Channel provider expiry bounds stale loading when no manager owns the connection.
- Thread finished Work retained in Toolkit State lets a new owner restore `active`
  after an interrupted clear.
- Presence lease expiry permits another Gateway replica to take over.
- Existing active Work is preserved through the Toolkit State data migration.
- Existing Slack installations must apply the generated manifest and reinstall before
  thread presence can succeed.
- Rollback stops the new manager and leaves provider status to explicit clear or
  provider expiry; the schema and Agent installation changes remain forward-compatible
  with ordinary Tracker and reply delivery.

## Observability

Structured logs identify provider, connection, presence API kind, desired state,
outcome class, and sanitized error code without message content, Bot token, raw
provider response, participant name, or thread title.

Unit tests expose deterministic manager desired/observed transitions. The Slack
provider fake exposes sanitized status operations and current status by App/channel/
thread for E2E assertions.

## Test Strategy

### E2E primary verification

One required Slack scenario covers both configured locations:

- ordinary all-messages input starts native presence with no Tracker;
- unfinished Todo publication creates one Plan with both actions;
- a later explicit invocation does not duplicate the Tracker;
- final reply is delivered at the current channel or thread target before Tracker
  deletion;
- presence clears on finish;
- Gateway restart restores still-active presence; and
- no settings-only control is emitted.

The Slack fake must support and record both status methods, Agent-mode manifest
evidence, provider rejection injection, and sanitized status inspection. No live
Slack credentials are required.

### Backend verification

- Work schema migration and validation preserve active/finished cycles.
- Presence coordinates initialize, fill once after provisioning, remain stable within
  a cycle, and replace with a new cycle.
- Presence lease claim, renewal, loss, configuration fencing, active renewal,
  finished clear, restart recovery, and isolated provider failure are deterministic.
- Channel and thread status clients classify success, `feature_disabled`, missing
  scope, credentials, rate limit, and ambiguous transport outcomes.
- Slack ordinary all-messages Work starts hidden; explicit invocation starts visible.
- Todo and late-invocation promotion create exactly one Tracker.
- Conversational Trackers contain both actions; Scheduled Trackers remain unchanged.
- Settings-only intent and provider delivery are absent.
- Routing parity tests cover response modes, exact Binding precedence, self-message
  exclusion, history scope, and final target.

### Quality and CI

- Backend Ruff, format, type checks, migration tests, focused tests, and full pytest.
- Testenv Ruff, format, type checks, and targeted required E2E.
- Required CI remains the final integration gate.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Slack always-visible conversational Work classification | `slack-260829/REQ-2` | invocation-based visibility shared with Discord | ingress provisioning and mailbox acceptance classifiers | unit and E2E ordinary/explicit matrix |
| Slack settings-only control after eligible invocation | `slack-260829/REQ-3` | signed settings action on visible conversational Tracker | ingress intent, payload, renderer, provider-control tests | grep plus E2E absence |
| No Slack Work presence lifecycle | `slack-260829/REQ-1` | leased channel/thread presence reconciliation | Gateway runtime, repository, SDK boundary, test fake | restart and finish E2E |
| Conventional Slack manifest without Agent declaration | `slack-260829/REQ-6`, `slack-260829/ADR-D2` | required Agent declaration and read-only provider surface | manifest guidance and validation | manifest unit tests |
| Channel Work Toolkit State schema version 2 | `slack-260829/REQ-1`, `slack-260829/ADR-D3` | schema version 3 with nullable Slack presence coordinates | migration, state model, fixtures | migration and state validation tests |
| Unfenced or process-local-only presence alternatives | `slack-260829/ADR-D3` | dedicated per-connection presence lease | External Channel Gateway runtime | multi-owner manager tests |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Work schema version 3 retains Slack presence anchor and initiator without changing mapping | `slack-260829/REQ-1`, `REQ-5`; `slack-260829/ADR-D1`, `ADR-D3` | `derived` |
| M2 | Parent-channel Work projects channel-based AI loading at the trigger message | `slack-260829/REQ-1`, `REQ-5`; `slack-260829/ADR-D1` | `decided` |
| M3 | Thread Work projects native Agent Session status on the exact bound thread with no fallback | `slack-260829/REQ-1`, `REQ-5`, `REQ-6`; `slack-260829/ADR-D1`, `ADR-D2` | `decided` |
| M4 | A dedicated per-connection presence lease owns reconciliation, renewal, clear, and handover | `slack-260829/REQ-1`, `REQ-4`; `slack-260829/ADR-D3` | `decided` |
| M5 | Slack visibility, promotion, identity, update, and deletion match Discord | `slack-260829/REQ-2`, `REQ-3`, `REQ-4`; `slack-260829/ADR-D4` | `required` |
| M6 | Conversational Tracker owns both actions and replaces settings-only invocation controls | `slack-260829/REQ-3`; `slack-260829/ADR-D4` | `decided` |
| M7 | Provider-neutral routing parity is audited and corrected without changing current mapping | `slack-260829/REQ-5`, `REQ-7`; current External Channel Specs | `required` |
| M8 | Manifest, scope validation, read-only Agent surface, and SDK version establish the required provider capability | `slack-260829/REQ-6`; `slack-260829/ADR-D2` | `decided` |

## Authority Audit

- Every Requirement maps to at least one material mechanism.
- Every mechanism is authorized by confirmed Requirements, accepted decisions, or
  unchanged current Specs.
- Presence remains derived presentation and creates no competing Work, Session,
  routing, or health authority.
- The Agent-owned provider surface is limited to the accepted prerequisite and does
  not authorize App Home ingress.
- No compatibility fallback, optional presence mode, or second Tracker lifecycle is
  introduced.

Authority result: **pass for Design revision 1**.

## Feasibility Validation

- The ingress locator already carries Slack trigger timestamp and provider user
  identity needed to initialize presence coordinates.
- Resource type and retained thread labels distinguish parent-channel and exact-thread
  targets without reinterpretation.
- The Gateway runtime already supervises lease-owning provider managers and can host
  one additional isolated manager.
- Slack SDK 3.44.0 exposes both required public methods.
- Current manifest generation and scope validation own installation readiness.
- Channel Work state is versioned Toolkit State and can be migrated in place.
- Existing Tracker effect planning already supports provider-neutral hidden promotion,
  complete Slack Block Kit replacement, actions, and final-reply-gated deletion.
- Testenv already owns a deterministic Slack provider fake and Gateway restart
  scenario support.

Feasibility result: **feasible for Design revision 1**.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-08-29`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5, M6, M7, M8`
- Approved scope: Require Slack Agent mode, project parent-channel and thread Work
  presence through target-appropriate public Slack APIs, make Slack Tracker and
  settings behavior match the completed Discord lifecycle, preserve current
  channel/thread mapping and routing semantics, audit provider-neutral message
  routing parity, and implement without further intermediate approval stops.
