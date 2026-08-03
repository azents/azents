---
title: "External Channel Session and Discord Thread Automatic Titles Design"
created: 2026-08-03
updated: 2026-08-03
tags: [external-channel, session, discord, slack, title, backend, testenv]
document_role: primary
document_type: design
snapshot_id: title-260802
implemented: 2026-08-03
---

# External Channel Session and Discord Thread Automatic Titles Design

- Snapshot: `title-260802`
- Document reference: `title-260802/DESIGN`
- Requirements: [`title-260802/REQ`](../requirements/title-260802-external-channel-automatic-title.md)
- Decisions: [`title-260802/ADR`](../adr/title-260802-external-channel-automatic-title.md)
- Mode: Collaborative
- Decision owner: requester

## Current Behavior and Gap

Direct Session input already owns the two-phase `auto_initial` to `auto_generated`
title lifecycle. External Channel history identifies the exact human
`authorized_invocation`, but the title helper accepts only `user_message` Events.

Discord root-message delivery creates or reuses one thread and stores its delivery
channel in the existing Resource labels. Direct creation uses a bounded Agent-derived
name. The current system does not retain whether that delivery thread was directly
created by Azents or attempt a later name update.

## Requirement and Decision Traceability

| Requirements | Decisions | Mechanism |
| --- | --- | --- |
| REQ-1, REQ-2 | D1 | M1 creation-marked mailbox and authorized External Channel title extraction |
| REQ-3, REQ-4, REQ-5 | D2 | M2 minimal direct-create evidence in existing Resource labels |
| REQ-4, REQ-5, REQ-6, REQ-7 | D3 | M3 one post-commit GET-and-conditional-PATCH attempt |

## Architecture and Ownership

The existing Session columns remain the only Session-title source of truth. The
canonical External Channel mailbox remains the one-time creation boundary. The
existing Resource remains the Discord delivery target and carries only the minimal
optional direct-create evidence needed for the one-shot operation.

There is no projection aggregate, retry state, attempt record, outbox, queue, Worker
scan, background reconciler, feature flag, or new runtime mode.

## M1. Creation-Marked External Channel Title Input

When synchronous admission creates the root Session and Binding, its existing mailbox
payload sets one `initial_title_eligible` marker. Reused Sessions and later
invocations leave the marker false. Access-approved creation uses the same mailbox
construction path and marker rule.

During mailbox promotion, an eligible payload selects only the Event whose Binding and
provider-message key match the payload trigger and whose author is a human
`authorized_invocation`. Its body plus bounded attachment filename and media-type
metadata becomes the existing initial-title input. Context-only messages, Bots, Agent
output, tool results, provider identifiers, secrets, and attachment contents are
excluded.

The initial title update commits with normal Event promotion. Mailbox deletion consumes
the marker. The existing title-generation scheduling and manual-title fences remain
unchanged.

## M2. Minimal Direct-Create Evidence

Discord thread creation returns whether the provider POST itself produced the usable
thread and the exact normalized name sent in that POST.

Only a direct successful create records the following in the existing Resource labels
beside the existing delivery channel:

- the delivery thread channel ID; and
- the exact initial provisional thread name.

An existing thread or a thread found only while reconciling an ambiguous create result
retains the delivery channel but not the provisional-name marker. Recording another
delivery channel never manufactures or replaces eligibility. No schema migration is
required.

## M3. One-Shot Discord Rename

After the exact `auto_initial` to `auto_generated` Session-title replacement commits,
`SessionTitleService` invokes one best-effort helper only when the generation Event is
an External Channel Event.

The helper:

1. loads the Event's exact connected Binding and Resource for the Session;
2. requires an active Discord connection, current route and Agent, current credentials,
   a retained delivery thread ID, and the direct-create provisional-name label;
3. reads that Discord thread once;
4. stops successfully without PATCH when the current name already equals the final
   title;
5. stops without mutation when the current name differs from the retained provisional
   name; and
6. otherwise immediately sends one name-only PATCH with the final automatic title.

The generated Session title already satisfies the tighter existing title bound. The
Discord helper still applies provider-valid normalization and rejects an empty result.
No later Session-title operation calls this helper.

## Failure, Retry, and Concurrency

Any missing state, thread-not-ready race, lifecycle change, provider rejection, rate
limit, timeout, cancellation, ambiguous response, or process interruption ends the
operation. The provisional title remains. There is no retry, recovery, backfill, or
second trigger.

The successful Session-title database commit precedes provider I/O. Provider failure
therefore cannot roll back the Session title or affect admission, wake, AgentRun
creation, Agent output, or ordinary External Channel delivery.

Discord has no conditional thread-name update. The helper minimizes but cannot remove
the race between the matching GET and adjacent PATCH and claims no stronger guarantee.

## Security and Observability

The helper uses current operation-scoped Discord credentials and validates the exact
Session, Binding, Resource, route, Agent, connection, Guild, and thread identities.
Provider credentials, message bodies, attachment contents, provisional names, and
final titles are not logged. Sanitized logs may record identifiers, operation outcome,
and provider failure category through the existing logger integration.

## Migration, Rollout, and Rollback

No database migration or backfill exists. Deployment activates the behavior only for
new creation-marked mailboxes and new directly created Discord threads. Existing
Sessions, mailboxes, Bindings, Resources, and threads remain unchanged.

Rollback removes the new code paths. Optional Resource-label metadata is inert and
safe for older code to ignore.

## Test Strategy

Deterministic tests cover:

- new Slack and Discord Sessions consuming only their exact authorized human trigger;
- context, Bot, tool, secret, provider-identifier, and attachment-content exclusion;
- safe attachment filename and media-type inclusion;
- later invocations and reused Sessions remaining ineligible;
- direct Discord create recording the exact provisional label while existing and
  ambiguous-recovered threads do not;
- successful GET-and-PATCH, already-final no-op, human-title takeover no-op, missing
  thread, lifecycle loss, provider failure, cancellation, and no retry;
- immediate Session execution and normal delivery independence; and
- one focused public-boundary Slack and Discord journey using the credential-free
  provider fake without direct database writes.

The required deterministic E2E lane remains the CI authority. No live Discord
credential is required.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Creation-marked canonical mailbox authorizes one exact External Channel Event to enter the existing automatic-title lifecycle | REQ-1, REQ-2, ADR-D1 | `decided` |
| M2 | Existing Resource labels retain only direct-create delivery identity and exact provisional name | REQ-3, REQ-4, REQ-5, ADR-D2 | `decided` |
| M3 | The winning final automatic-title commit performs one post-commit GET-and-conditional-PATCH attempt with no recovery | REQ-4, REQ-5, REQ-6, REQ-7, ADR-D3 | `decided` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| `user_message`-only initial-title extraction | REQ-1 | M1 closed authorized External Channel extraction | Session title and mailbox promotion helpers | Later/context/Bot Events remain ineligible in tests |
| Agent-name-only Discord thread lifecycle | REQ-4 | M2 direct-create marker plus M3 one-shot final title attempt | Discord delivery and Session title service | Existing/ambiguous threads receive no marker or PATCH |
| Durable projection/retry design from the closed PR stack | Requester clarification and ADR-D1 through D3 | None | No projection schema, repository, Worker drain, retry state, attempt record, or plan enters this branch | Diff and migration audit |

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-08-03`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3`
- Approved scope: creation-marked External Channel Session titles, minimal
  direct-create Discord Resource-label evidence, and one post-commit best-effort
  GET-and-conditional-PATCH attempt without retry or recovery state.
