---
title: "Session Model Change"
created: 2026-08-19
updated: 2026-08-19
tags: [model, session, chat, frontend, backend, engine, architecture]
document_role: primary
document_type: adr
snapshot_id: model-260819
---

# Session Model Change

- Snapshot: `model-260819`
- Document reference: `model-260819/ADR`
- Requirements: [`model-260819/REQ`](../requirements/model-260819-session-model-change.md)

## Context

A Session currently stores one complete resolved inference snapshot containing its label, effort, physical model selection, model-scoped settings, effective context limits, and resolution time. The worker reuses that snapshot whenever a later input has the same label and effort. This makes an existing Session retain stale physical configuration when an administrator changes the Agent option behind that label.

The same field group also serves two incompatible roles: the user-visible profile intended for the next model turn and the immutable snapshot required to finish or recover a provider call that has already been prepared. A model-only change during an active call requires both states to exist simultaneously.

Explicit human profiles are currently applied during asynchronous mailbox promotion. A later direct Session profile update could therefore be overwritten when an older queued message is eventually promoted. The new capability needs one authoritative ordering model across message sends and model-only changes without creating a transcript input, Run, or provider call for the model-only case.

## Decision Map

### Fixed or derived outcomes

- The Session durably owns its applied model label and reasoning effort across every execution trigger.
- Clients submit only Agent-owned labels and supported effort values; physical model snapshots remain server-owned.
- The current provider call remains immutable, while the next model-turn boundary uses the latest Session intent and current Agent mapping.
- Agent main-label changes do not overwrite an existing Session label.
- Model-only application creates no message, command, transcript event, Run, or provider call.
- Web, external-channel, Scheduled Task, command, continuation, and other implicit execution paths share the Session state without their own picker or invocation override.
- Human profile mutation remains root-Session only; subagent Sessions remain read-only.
- Browser-local model-profile persistence is removed without compatibility behavior.
- The existing Composer picker location and reviewed V2 pending-state treatment remain fixed.

### Pending material decisions

- [x] `model-260819/ADR-D1`: dedicated idempotent Session model-profile replacement with Session-lock ordering and response-driven convergence.
- [x] `model-260819/ADR-D2`: AgentSession owns separate applied intent and prepared-turn recovery state.
- [x] `model-260819/ADR-D3`: pull and re-resolve current Session intent and Agent mapping at every fresh main-model turn boundary.
- [x] `model-260819/ADR-D4`: validate and apply explicit human profiles at admission under the Session lock.
- [x] Active-Run reconciliation is derived by `model-260819/ADR-D3`; no separate D5 decision or signaling state is introduced.
- [x] `model-260819/ADR-D6`: fail closed on late profile-resolution drift without rollback or fallback.

### Agent-owned implementation categories

- Domain type and DTO names after ownership is decided.
- SQL constraint and index names.
- Helper/module boundaries and exact file layout.
- Equivalent local comparison or retry helpers that add no new persisted authority or mode.
- CSS implementation of the approved visual treatment.
- tRPC wiring, fixture identifiers, Storybook story names, logging field names, and generated-client mechanics.

## model-260819/ADR-D1. Use a dedicated idempotent Session model-profile replacement

Add a dedicated full-replacement endpoint:

```http
PUT /chat/v1/sessions/{session_id}/model-profile
```

The request contains one Agent-owned `model_target_label`, nullable
`reasoning_effort`, and a required `client_request_id`. The endpoint is the only
model-only human mutation boundary. It authorizes an active root Session, validates
the label and effort against the current Agent options, and replaces the Session's
applied intent under the Session row lock.

Idempotency is scoped by `(session_id, requester_user_id, client_request_id)`.
Reusing a key with the same normalized payload and mutation type returns the original
authoritative result. A different payload or mutation type returns a conflict. The
concrete idempotency record and accepted-result storage are implementation details.
Requiring the key prevents a late retry after an ambiguous response from silently
reversing a later successful profile change.

Competing admitted profile mutations serialize by database lock acquisition and
commit order. The later committed full replacement wins; HTTP arrival order is not
authority. Replacing the profile with its current value is a semantic no-op but
still returns the canonical applied-profile response.

Success commits only the applied Session intent. It creates no mailbox row,
transcript event, pending command, Run, wake-up, provider call, or queued-switch
state. Invalid labels or unsupported effort values fail before mutation and preserve
the previous applied intent.

The response contains only `session_id`, `model_target_label`, and
`reasoning_effort`. It never exposes a physical model, provider, integration, or
credential. The initiating frontend applies the response and invalidates/refetches
the Session query. No new WebSocket control frame is added: ordinary Session
refetch/resynchronization is sufficient for other clients to converge, and immediate
cross-tab push is outside the confirmed Requirements.

### Rejected alternatives

- **Overload the Composer input endpoint with a model-change action:** this would
  mix a transcript-free, no-Run Session setting mutation into mailbox input
  semantics and risks creating a delayed queued-switch mode.
- **Use a non-idempotent direct patch:** state replacement alone is repeatable, but
  it cannot distinguish a legitimate retry from a late retry that would reverse a
  later committed user choice.
- **Publish a new live control frame:** this adds a new public real-time contract
  without authority from the confirmed cross-browser reload requirement.

## model-260819/ADR-D2. Separate applied Session intent from prepared-turn recovery state

AgentSession owns two independent durable states:

1. **Applied Session intent:** an Agent-owned model target label and nullable
   reasoning effort. This is the authoritative API/UI state and the input to future
   model-turn preparation.
2. **Prepared-turn recovery snapshot:** the complete physical
   `AgentModelSelection`, model-scoped settings, effective context and compaction
   limits, resolution timestamp, and the label and effort used by that prepared
   turn. This is internal authority for the current provider call and interrupted
   or recoverable Run.

The existing complete `current_*` database column group is retained as the internal
prepared snapshot for this snapshot. It is not moved to AgentRun and is not removed.
Domain and repository models must expose it explicitly as prepared state rather than
as the user-visible Session choice. The existing all-null or complete-state
constraint remains the invariant for this prepared group.

New nullable applied-label and applied-effort columns are added. A non-null applied
label owns a nullable effort, where null means model Default. Public Session
projections read only these applied fields. The physical prepared model, settings,
limits, and resolution time remain absent from public Session responses and
generated clients. Existing public
`current_model_target_label` and `current_reasoning_effort` response field names are
retained for contract stability, but their source changes to the applied intent.

The forward migration copies the existing prepared label and effort into the new
applied fields for every Session with a complete current inference state. The
complete physical snapshot remains in place as prepared recovery authority. A
Session whose current state is entirely null keeps both applied intent and prepared
state null, preserving Agent main/default inheritance until its first explicit
application or model-turn preparation. A partial legacy state is not guessed or
repaired; migration validation fails closed and requires operational diagnosis.

No inference snapshot is added to AgentRun. AgentRun remains a multi-turn lifecycle
record, while AgentSession remains the single durable owner of the currently
prepared turn needed for recovery.

The migration and application code deploy together. Mixed-version operation is not
supported because an older binary would misinterpret the retained `current_*`
prepared fields as the applied Session choice after new writes diverge the two
states. Database downgrade is safe only before feature traffic writes the new
semantics; after that boundary, rollback requires a compatible deployment and
database snapshot or forward repair rather than reusing the old interpretation.

### Rejected alternatives

- **Move prepared state to AgentRun:** AgentRun spans multiple model turns, so this
  requires a new per-turn identity, version, or table and expands the lifecycle
  without improving the confirmed Session-level recovery boundary.
- **Keep prepared state only in process or Redis:** this loses authoritative recovery
  after worker/process loss and conflicts with PostgreSQL execution authority.
- **Continue using one combined Session state:** a concurrent next-turn intent
  change and immutable in-flight provider snapshot cannot both be represented
  correctly.

## model-260819/ADR-D3. Resolve current Session intent at every fresh main-model turn boundary

Before every fresh main-model provider dispatch, the worker reads the latest
Session applied intent and resolves its label through the current Agent selectable
option. It does not push Agent configuration changes into Session rows and does not
add an Agent model-configuration revision, dirty flag, queued control item, or
profile-change wake-up.

A fresh boundary is:

- immediately before the first main-model provider dispatch of a new Run; or
- after a previous model call has completed and the same Run requires another
  main-model turn, including follow-up after client-tool results and continuation
  work.

Context compaction and other lightweight-model dispatch remain outside the Composer
profile and continue to use the Agent lightweight mapping.

A provider retry, retry backoff, or recovery of the same already prepared logical
model call is not a fresh boundary. The in-memory `RunRequest` or durable prepared
snapshot remains authoritative for that attempt. Process or worker loss therefore
does not change the model behind an already prepared call. A failure before a
prepared snapshot has been committed may restart fresh preparation.

When applied intent is null, a fresh boundary derives temporary turn intent from
the current Agent main label and default reasoning setting. It does not materialize
that inherited default into the applied-intent columns. The prepared snapshot
records the concrete label, effort, and physical configuration for recovery, while
the public applied fields remain null. A later Agent default change therefore
naturally affects the next fresh boundary until the Session receives an explicit
applied intent.

Preparation may perform model and integration resolution outside the final lock
transaction. Before committing the candidate, it re-reads and locks the owning
Agent and Session in the canonical order and verifies that:

- the Session applied label and effort still match the candidate input; and
- the relevant Agent selectable option or inherited default mapping still matches
  the candidate.

If either changed or is concurrently changing, the candidate is discarded and
preparation retries from current state. Only a successfully resolved and coherently
revalidated candidate replaces the complete prepared snapshot. That commit is the
linearization boundary for the model turn; later Session or Agent mutations apply
to the following fresh boundary. Resolution failure never overwrites the previous
prepared snapshot.

This boundary pull fully determines active-Run reconciliation. A model-only mutation
does not need a wake-up, mailbox row, dirty flag, or internal control item. An
in-flight provider call finishes with its existing request, the next fresh boundary
pulls current state, and an idle Session starts no Run until ordinary work arrives.

### Rejected alternatives

- **Resolve only when a revision or fingerprint changes:** this introduces another
  persisted authority and migration while every boundary still needs to observe
  current Session intent and Agent state.
- **Fan out Agent option changes to Sessions:** this creates large locking and race
  surfaces, duplicates physical snapshots, and risks overwriting Session-owned
  label intent.
- **Signal active Runs with a queued control item or dirty flag:** the required
  behavior is already achieved by an unconditional fresh-boundary pull without a
  user-visible delayed-switch mode.

## model-260819/ADR-D4. Apply explicit human profiles atomically at input admission

Every explicit human input profile is validated and applied to the Session
applied-intent fields during admission, in the same Session-lock transaction that
admits its message, edit, or TurnAction. A first-message request atomically creates
the root Session, applies the intent, admits the mailbox work, and records
idempotency. Worker promotion never overwrites applied Session intent from an older
mailbox profile.

Mailbox requested label and effort and durable
`requested_inference_profile` event data remain immutable historical request
association. They are not Session state or actual turn provenance. The actual
model-turn profile is the prepared result from `model-260819/ADR-D3` and may differ
from an older queued request when a later profile mutation commits before provider
dispatch.

All explicit input-profile writes and model-only replacements serialize under the
Session lock and commit order. A later committed profile wins over an older queued
message. Earlier queued implicit external-channel, Scheduled Task, command, or
continuation work carries no profile authority and uses the latest applied Session
intent at its eventual fresh model-turn boundary. Mailbox and transcript FIFO order
remain unchanged.

Label and effort validation, attachment claim, idempotency, access, active-state,
and Session creation failures roll back the input admission and applied-intent
change together. Once admission commits, later action execution failure,
preparation failure, or user deletion of the pending mailbox item does not undo the
Session model setting that the user already applied.

Only a newly accepted idempotent write mutates applied intent. A retry that resolves
to an existing accepted request returns its original result without reapplying its
historical profile, so a delayed retry cannot revert a newer Session choice. A
payload or mutation-type mismatch for the same key remains a conflict.

Cutover uses a coordinated drain. Old writers and workers are quiesced, every
pre-cutover mailbox row carrying an explicit profile is allowed to drain or
terminalize under the old promotion semantics, and the deployment verifies that no
such rows remain before running the applied-intent migration and enabling new code.
Implicit null-profile rows may remain because they do not own a profile and will use
the migrated latest Session intent. If explicit rows cannot be drained, cutover
aborts rather than guessing or backfilling potentially stale or invalid intent.

### Rejected alternatives

- **Queue model-only changes as internal mailbox items:** this creates the delayed,
  queued-switch mode excluded by the model-only application contract.
- **Keep promotion-time application with an intent revision fence:** this adds a
  second ordering authority and makes an older message conditionally capable of
  mutating newer Session state.
- **Backfill pending explicit mailbox profiles during cutover:** this can promote
  requests that legacy processing would have rejected and cannot preserve the
  established safe-failure boundary reliably.

## model-260819/ADR-D6. Fail closed when applied intent becomes unresolvable

When a fresh model-turn boundary cannot resolve the Session applied intent through
the current Agent configuration, it fails closed before provider dispatch. This
includes an unknown, deleted, or renamed label; a newly unsupported effort; an
invalid current model option; and typed unavailable integration or configuration
failures.

Expected resolution failures follow the existing typed pre-provider failure
boundary. They persist a user-safe failure or `system_error`, consume or
terminalize the currently admitted work according to that established path, and
must not leave deterministic-invalid FIFO work blocking later work. The failure may
carry the logical applied label and effort, immutable requested-profile provenance,
and a safe typed discriminator, but it records no new physical model or provider
provenance because no prepared candidate committed and no provider dispatch
occurred. If a same-Run follow-up turn fails, the Run becomes terminal through the
normal failure path while all earlier successful turns remain durable. If first-turn
preparation fails before a Run would normally start, it uses the existing durable
failure-event/no-provider boundary.

Applied Session intent remains unchanged even when it is no longer resolvable. The
system does not restore a previous profile, substitute the Agent default, choose
another label, migrate an alias, or copy a physical snapshot into intent. The
previous prepared snapshot also remains unchanged for recovery and diagnosis, but
it is authoritative only for the already prepared logical call and its retry. It
must never be used to dispatch the failed fresh turn.

Previously admitted messages, edits, TurnActions, external-channel work, Scheduled
Task work, commands, and continuations remain admitted. Their historical requested
profile provenance is not rewritten and admission is not retroactively rejected.
Deterministic late drift receives the typed failure boundary rather than automatic
retry or replay.

Unexpected database, process, or infrastructure exceptions retain their existing
transaction rollback and pending retry/recovery semantics. A retry that returns to
a fresh boundary resolves current Session and Agent state again; it does not fall
back to the stale prepared snapshot.

After a user applies a valid profile or an administrator restores the Agent mapping,
a later ordinary input, supported explicit retry, or external/scheduled trigger
starts a fresh resolution and may succeed. Repair alone does not wake the Session,
start a Run, or replay consumed work.

The UI keeps the server-owned applied label and effort visible exactly as stored and
uses the existing typed failure projection. No fallback picker value, silent
default, special invalid-profile mode, delayed switch, or new WebSocket/status
contract is introduced.

### Rejected alternatives

- **Roll back to the prior applied intent:** this requires additional intent history
  and races with newer committed choices while overriding the user's durable
  selection.
- **Execute with the prior prepared snapshot:** this violates current Agent mapping
  authority and treats recovery state as a silent fresh-turn fallback.
- **Substitute Agent default or another label:** this hides invalid configuration,
  changes Session label intent, and contradicts the explicit no-fallback scope for
  deleted or renamed labels.
