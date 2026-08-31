---
title: "External Channel Input Request Action"
created: 2026-08-31
tags: [external-channel, agent, continuation, reliability, architecture]
document_role: primary
document_type: adr
snapshot_id: channel-260831
---

# External Channel Input Request Action ADR

- Snapshot: `channel-260831`
- Document reference: `channel-260831/ADR`
- Requirements: [channel-260831/REQ](../requirements/channel-260831-request-input-action.md)

## Context

Channel Work currently has only active and finished lifecycle states. The External
Channel idle hook treats every active Work as a continuation source, while finish and
ignore terminate the Work. This leaves no authoritative state for active work that has
asked a participant a question and should wait for ordinary channel input.

A transient current-Run suppression is insufficient because another continuation
source can create a Run before the participant replies. Finishing Work is also not a
valid representation because it discards the distinction between completed work and
work blocked on participant input.

## Decisions

### `channel-260831/ADR-D1` — Add `request_input` with orthogonal awaiting state

**Affects:** `channel-260831/REQ-1`, `channel-260831/REQ-2`

`channel_action` gains the explicit nonterminal mode `request_input`. It publishes an
ordinary question or feedback request while preserving the selected binding's active
Work cycle. Awaiting participant input is stored as an orthogonal per-binding Work
state, not as a terminal status and not as a Session-global pause.

The awaiting state survives process restart, retry, recovery, and compaction. It is
excluded from provider-neutral public progress tasks and does not create a new
provider-specific interaction contract.

Rejected alternatives:

- Finishing or silently ignoring the Work misrepresents unfinished work and forces the
  Agent to reconstruct progress after the response.
- Suppressing only the requesting Run allows Goal, Scheduled Task, TurnAction, or
  another source to create an intervening Run that re-enables the unwanted External
  Channel continuation before participant input.
- Adding a third terminal-style Work status couples input waiting to Work lifecycle
  and expands management contracts that only need active versus finished.

### `channel-260831/ADR-D2` — Resume only from same-binding input or continue

**Affects:** `channel-260831/REQ-3`

Awaiting state is cleared by either of two authoritative same-binding transitions:

1. creation of canonical mailbox input for an eligible human External Channel message
   through that binding; or
2. an explicit `channel_action continue` on that binding.

A continue action invalidates both established awaiting state and any older in-flight
input-request settlement. Activity on another binding and non-External-Channel Run
sources do not resume the waiting Work. Finish and ignore retain their existing
terminal semantics.

Rejected alternatives:

- Clearing on any next Run conflates participant input with unrelated autonomous
  continuation sources.
- Clearing from another binding violates binding-scoped Work ownership.
- Requiring provider-native reply correlation introduces provider-specific state and
  rejects otherwise valid ordinary channel responses.

### `channel-260831/ADR-D3` — Confirm delivery before waiting and fail open

**Affects:** `channel-260831/REQ-4`

The initial action commits the ordinary reply plan and preserves ready continuation
state. Awaiting state becomes authoritative only after all required question reply
parts are confirmed delivered. Failed, unknown, or not-attempted delivery leaves the
Work ready for normal continuation.

Awaiting settlement is fenced by the exact Work cycle and canonical state revision
captured by the input-request action. Same-binding participant admission and continue
advance that revision. A late delivery result from the older request therefore cannot
restore awaiting state after newer activity.

Rejected alternatives:

- Persisting awaiting state before provider delivery can strand Work behind a question
  the participant never received.
- Treating ambiguous delivery as success prefers silence over recoverable duplicate
  communication.
- Allowing an unfenced late result to restore awaiting state can override a newer
  explicit continue action or participant response.

### `channel-260831/ADR-D4` — Use a coordinated backend restart for rollout

**Affects:** `channel-260831/REQ-2`, `channel-260831/REQ-3`

The Channel Work Toolkit State schema upgrade and `request_input` mode are deployed
through a coordinated restart of every backend component that reads or writes Channel
Work Toolkit State. This includes Channel Action and idle-continuation workers,
External Channel ingress, management and API readers, Slack Work presence managers,
and Discord Gateway typing managers. The version-4 state migration runs before the
homogeneous new backend begins serving the mode.

The rollout does not add temporary version-3/version-4 dual-read behavior, a feature
flag, or a generalized deployment-quiescence controller.

Rejected alternatives:

- A staged rolling rollout requires an additional compatibility phase, temporary
  schema readers, and later cleanup for a small binding-scoped feature.
- Exposing the mode during mixed-version execution lets an older worker ignore
  awaiting state and create the continuation the feature is intended to suppress.
- A generalized quiescence controller is broader than the bounded coordinated restart
  required for this state migration.

### `channel-260831/ADR-D5` — Add no new lock for awaiting transitions

**Affects:** `channel-260831/REQ-3`, `channel-260831/REQ-4`

Awaiting request, settlement, resume, and invalidation use the existing bounded
Channel Work Toolkit State CAS and canonical `state_revision`. The feature does not
add a database, row, table, advisory, Session, Binding, or long-lived transaction
lock. Existing authorization and lifecycle locks remain unchanged.

If implementation discovers that the approved behavior cannot be implemented with the
existing CAS boundary, it returns for requester review instead of adding a lock.

Rejected alternatives:

- A new Session or Binding lock recreates serialization around unrelated Channel Work
  activity.
- A table or advisory lock expands one binding-scoped lifecycle into a global
  coordination boundary.
- A long-lived transaction around provider delivery violates the existing
  commit-before-call boundary.

### `channel-260831/ADR-D6` — Stop active presence while awaiting input

**Affects:** `channel-260831/REQ-2`, `channel-260831/REQ-3`

Awaiting Work remains active and keeps its Channel Work Tracker, but it is not
presented as actively processing. Slack Work presence projects the Work as idle, and
Discord Gateway typing excludes it. Same-binding admitted input or continue clears
awaiting state, after which the existing presence managers may project processing
again.

Rejected alternatives:

- Continuing processing presence or typing while waiting misrepresents who must act
  next.
- Deleting the Work Tracker discards useful task and progress context.
- Adding a provider-specific waiting control violates the ordinary-message-only
  interaction boundary.

### `channel-260831/ADR-D7` — Extend the existing Agent-facing prompt structure

**Affects:** `channel-260831/REQ-1`

`request_input` follows the existing `channel_action` guidance structure instead of
introducing a new prompt surface. The static Toolkit prompt adds only a concise
pre-discovery reference to requesting participant input. The Tool description owns
the mode-selection meaning, the `mode` and `message` field schemas own their concise
per-field guidance, and runtime validation enforces the corresponding input rules.

The guidance states that `request_input` asks for required participant input, pauses
automatic continuation for only that binding without finishing Work, and resumes from
same-binding participant input or `continue`. It remains comparable in length and
specificity to the existing `finish`, `continue`, and `ignore` guidance. No dynamic
prompt, separate instruction block, mode-specific Skill, or second model-facing
contract is added.

Rejected alternatives:

- A new dynamic prompt duplicates stable Tool usage guidance and creates another
  prompt ownership boundary.
- A separate instruction block or Skill makes one mode structurally different from
  the existing `channel_action` modes.
- Validation without model-facing guidance enforces argument shape but does not tell
  the Agent when to select the mode.
- A verbose lifecycle playbook adds prompt weight and makes the new mode inconsistent
  with the concise existing mode descriptions.

## Consequences

- Channel Work remains active and retains its title, tasks, Tracker, and cycle identity
  while participant input is awaited.
- Idle continuation selection becomes binding-aware and excludes only awaiting Work.
- Existing External Channel ingress becomes the resume authority; no Discord or Slack
  interactive webhook surface is introduced.
- Awaiting Work stops Slack processing presence and Discord typing without deleting
  its Tracker.
- The persisted Channel Work Toolkit State schema requires a versioned migration.
- Deployment requires one coordinated restart of Channel Work and idle-continuation
  state readers and writers before the new mode is used.
- Concurrency remains inside the existing Toolkit State CAS and Work revision boundary;
  no new lock is added.
- Scheduled Task-bound Channel Actions continue to use their separate cycle lifecycle
  and do not accept `request_input`.
- A provider ambiguity may produce an additional continuation, but cannot silently
  suspend Work on an unconfirmed question.
- Agent guidance remains in the existing static prompt, Tool description, field
  schema, and validator boundaries; no new prompt structure is introduced.
