---
title: "External Channel Session and Discord Thread Automatic Titles"
created: 2026-08-02
updated: 2026-08-02
tags: [external-channel, session, discord, slack, title, architecture]
document_role: primary
document_type: adr
snapshot_id: title-260802
---

# External Channel Session and Discord Thread Automatic Titles

- Snapshot: `title-260802`
- Document reference: `title-260802/ADR`
- Requirements: [`title-260802/REQ`](../requirements/title-260802-external-channel-automatic-title.md)
- Mode: Autonomous
- Decision owner: dedicated read-only autonomous design interviewee

## Context

Direct Session input currently enters a two-phase automatic title lifecycle. Promotion of the first `user_message` stores a deterministic `auto_initial` title and its Event identity. A best-effort lightweight-model call later replaces that value with `auto_generated` only while the same Event still owns the initial title. Manual titles remain authoritative and title generation never blocks Agent execution.

External Channel invocation batches instead promote source-attributed `external_channel_message` Events. The exact human message that authorized execution is already distinguished from surrounding provider history, but the title lifecycle currently ignores every External Channel Event. Discord thread provisioning also uses only the routed Agent name at creation time. Existing threads are preserved, and no durable state records whether an Azents-created thread still awaits its one initial Session-title projection.

One External Channel Resource has at most one connected Binding, while one AgentSession may contain multiple independent Bindings. Session membership therefore cannot by itself authorize a provider rename. Existing provider delivery attempts are durable at-most-once mutation records: failed and unknown outcomes are terminal, and they have no desired-state retry schedule. Discord thread rename is different because the current provider name can be read and the same desired name can be safely reconciled after interruption, subject to Discord's lack of an atomic compare-and-set operation.

The confirmed Requirements fix one-way, one-time product behavior. The remaining decisions define projection authority, convergence and retry semantics, and conservative provider ownership evidence.

## Fixed and Derived Outcomes

- Only the first human-authored External Channel message marked as the authorized invocation can become the existing initial automatic-title Event. Surrounding context, Bots, Agent output, and tool results remain excluded.
- Safe attachment names and media types may supplement that Event's title input without reading attachment content solely for title generation.
- The existing `auto_initial -> auto_generated` lifecycle, manual-title precedence, and non-blocking title generation remain unchanged.
- Discord thread creation continues immediately with a provider-valid provisional title derived from the selected routed Agent.
- Pre-existing threads and later Bindings do not inherit initial-title projection eligibility.
- A provider rename is a Worker-owned system operation and revalidates connection, route, resource, Binding, Session, Agent, credentials, and Discord target authority immediately before mutation.
- Later manual Session titles and later Discord thread names remain independent.
- Automatic Session titles are already shorter than Discord's maximum thread-name length; provider normalization cannot semantically rewrite a valid automatic title.
- No public API, generated client, frontend workflow, Slack provider mutation, Redis correctness dependency, or new deployment unit is introduced.

## Decision Backlog

- [x] Durable projection source of truth and transactional convergence boundary.
- [x] Provider retry, reconciliation, and terminal failure contract.
- [x] Discord thread creation ownership proof and human-takeover fencing.
- [x] Mixed-version provisioning ownership during rolling deployment and rollback.
- [x] Agent execution and ordinary Channel Action ordering relative to fenced provisioning.

## Accepted Decisions

### title-260802/ADR-D1 — A dedicated per-Resource aggregate owns initial title projection

Create one durable Discord initial-title projection aggregate for each eligible
External Channel Resource. The aggregate immutably retains the Binding and
AgentSession that caused the eligible thread creation and is the sole authority for
that Resource's one initial title projection.

The aggregate records two independently arriving readiness facts:

1. provider-confirmed Azents thread provisioning, including the exact thread identity
   and expected provisional name; and
2. the winning `auto_generated` Session title and its generation Event identity.

Each existing transaction updates its side of the same aggregate. Confirmed thread
provisioning records provider readiness in the delivery-channel persistence
transaction. The winning `auto_initial -> auto_generated` replacement snapshots and
arms every eligible aggregate for that Session in the same transaction as the Session
title update. Provider reconciliation becomes eligible only after both facts exist.

Affected requirements: `title-260802/REQ-2`, `title-260802/REQ-3`,
`title-260802/REQ-4`, `title-260802/REQ-6`.

This supports thread-first and title-first completion without a scan or another user
invocation. The creating Binding and Session remain explicit, so a later Binding
cannot inherit title ownership. One Session may arm several independently eligible
Resources, while each Resource has one bounded initial-title lifecycle.

Rejected alternatives:

- Store ownership and lifecycle state in Resource or Binding JSON labels. Labels are
  mutable routing and presentation metadata and cannot provide equally strong typed
  state, uniqueness, transaction, or disconnect/rebind provenance.
- Create only an existing delivery-attempt row after the title arrives. An attempt
  cannot represent pre-attempt ownership readiness or both arrival orders without
  inferring authority from mutable labels, and the current ledger owns provider
  attempts rather than pre-attempt desired state.
- Publish a generic durable Session-title outbox. The required eligibility is
  Resource- and creating-Binding-specific, so a generic event would expand Session
  title semantics and still require External Channel to reconstruct earlier provider
  ownership.

### title-260802/ADR-D2 — A desired-state reconciler retries while authority remains current

The existing Worker process owns a dedicated Discord initial-title reconciler. It
durably claims due projection aggregates and revalidates the complete projection,
connection, route, Resource, creating Binding, AgentSession, Agent, credential, and
provider-target authority before provider I/O.

For an armed projection, reconciliation reads the current Discord thread:

- the desired final title means the projection is already `applied`;
- the retained expected provisional title permits one PATCH toward the desired title;
- any other valid title means provider or human ownership has taken over and the
  projection becomes `relinquished`;
- revoked lifecycle authority relinquishes the projection without provider mutation;
  and
- permanent authorization, missing-target, malformed-target, or confirmed
  non-recoverable provider failures terminalize as `failed` or `relinquished`
  according to whether provider authority or title ownership disappeared.

Rate limits, Discord server failures, transport failures, cancellation, process
interruption, and ambiguous PATCH outcomes persist a retry with exponential capped
backoff. Every later attempt performs GET reconciliation before considering another
PATCH.

There is no fixed attempt-count exhaustion. Retry continues only while the projection
is armed and nonterminal and its creating Binding, Session, Agent, route, Resource,
connection, credential, and provider target remain authoritative. Successful
convergence, title takeover, lifecycle revocation, target disappearance, or permanent
provider rejection ends the retry lifecycle.

Affected requirements: `title-260802/REQ-4`, `title-260802/REQ-5`,
`title-260802/REQ-6`.

Rejected alternatives:

- Extend the current at-most-once delivery ledger and leave failed or unknown outcomes
  terminal. Thread name is readable idempotent desired state, so abandoning a rate
  limit, server failure, or ambiguous PATCH would violate recoverable projection
  without preventing a meaningful duplicate.
- Emit a new at-most-once delivery attempt for every retry. This creates an unbounded
  attempt chain while still requiring the aggregate to decide whether another
  mutation is valid, obscuring one desired-state lifecycle and human-takeover fence.

### title-260802/ADR-D3 — Bounded provider proof establishes one-time title ownership

Azents establishes initial-title ownership only through one bounded provider-evidence
sequence:

1. immediately before creation, read the Discord root message and prove no thread
   exists;
2. request thread creation with the exact normalized provisional Agent-derived name;
3. accept either a valid successful create response, or an ambiguous create followed
   immediately by a root-message read that returns a thread whose `owner_id` is the
   current connected Bot and whose name exactly equals that provisional title; and
4. persist the confirmed thread identity and expected provisional name in the
   projection aggregate.

A thread present during the preflight read, owned by another principal, named
differently, or lacking complete ownership evidence remains unmanaged. Resource labels
or name equality alone never establish title ownership.

After ownership is established, every reconciliation attempt reads the thread
immediately before mutation. The desired final title means `applied`, the exact
expected provisional title permits the PATCH, and any other current title terminally
relinquishes ownership without mutation.

Discord exposes no atomic compare-and-set for thread names. A human rename between the
final matching GET and the immediate PATCH can therefore be overwritten. Azents
performs no unrelated work in that interval, claims no stronger guarantee, stops after
the one initial projection, and never overwrites a later human rename through ongoing
synchronization.

Affected requirements: `title-260802/REQ-3`, `title-260802/REQ-4`,
`title-260802/REQ-5`, `title-260802/REQ-6`.

Rejected alternatives:

- Require only a successful create response. This abandons a provider-committed
  Azents create after response loss even when preflight absence, current Bot
  ownership, and exact provisional-name equality prove the bounded outcome.
- Infer ownership from Resource labels or the current name. Local labels are not
  provider proof, and a pre-existing human thread may coincidentally use the same
  name.

### title-260802/ADR-D4 — A durable protocol identity fences title-aware provisioning

A producer that creates a Discord initial-title projection candidate creates exactly
one title-aware thread-provisioning control under a new durable origin or operation
identity. That identity is deliberately outside every legacy Worker
provider-control claim predicate. Candidate-producing code does not also emit a
legacy control that can provision the same thread.

A current Worker:

1. claims the fenced provisioning row;
2. durably retains the exact provisional title and provisioning-attempt fence;
3. performs the D3 preflight, create, and reconciliation proof;
4. atomically records the Resource delivery-channel identity and projection provider
   readiness, requiring their thread identities to match; and
5. only after provider readiness is durable, creates or releases ordinary joined
   presence and progress controls that target the confirmed thread.

Old producers continue their legacy path and create no projection candidate or fenced
row. Current Workers remain compatible with legacy rows. Candidate existence is the
structural path selector; there is no feature flag, environment setting, Redis
authority, fallback path, or second runtime mode.

Rollout applies the additive schema and protocol identity before candidate producers.
During a mixed deployment, old Worker SQL predicates ignore fenced rows and cannot
mutate them. New Workers may process them and expose only provider-ready ordinary
controls to the shared legacy-compatible drain.

Application rollback does not remove or reinterpret the additive identity. Old
producers resume legacy behavior, while existing fenced rows remain inert and
nonterminal until a forward deployment resumes them after current authority
validation. Old code does not infer ownership from Resource labels or terminalize an
unknown fenced row. The additive database identity remains installed throughout the
compatibility window.

Affected requirements: `title-260802/REQ-3`, `title-260802/REQ-4`,
`title-260802/REQ-6`.

Rejected alternatives:

- Require a coordinated deployment and rollback barrier. Correctness would depend on
  perfect operational ordering across every producer and provider-control Worker,
  including delayed or restarted old processes.
- Let old Workers provision and reconstruct ownership later from Resource labels.
  Labels do not prove preflight absence, Bot ownership, provisional-name equality, or
  the creating Binding and Session, directly violating D3.

### title-260802/ADR-D5 — Provider target readiness gates Session execution

For a candidate-bearing Discord root-message conversation, the Session, Binding,
title candidate, projection, fenced provisioning state, and canonical External
Channel mailbox input commit immediately. The retained input is non-promotable, the
Session does not transition to running, and no broker wake is dispatched until the
projection records one usable canonical Discord delivery thread.

The fenced provisioning identity belongs to the new projection domain rather than
introducing unknown enum values into legacy delivery rows. A current Worker
reconciles one of two usable outcomes:

- `ready`: D3 proves Azents ownership, and the transaction records matching canonical
  Resource delivery identity and immutable projection ownership identity; or
- `unmanaged`: a pre-existing or insufficiently owned thread is preserved, title
  ownership is relinquished, and its usable identity becomes the canonical Resource
  delivery target.

Only that provider-readiness transaction may create ordinary joined-presence and
initial-progress controls already targeting the confirmed delivery thread, release
the retained input for promotion, mark the Session running, and establish the
post-commit wake obligation.

Automatic title generation and the later title PATCH do not participate in this
gate. After target readiness, Agent execution and title generation proceed
independently, and title projection failure never suspends or rolls back execution.

Transient provisioning failure keeps the admitted Session and input behind the gate
with persisted GET-first retry. Permanent inability to establish a usable target or
lifecycle revocation terminalizes provisioning and leaves the retained roots and
sanitized evidence for diagnosis without reporting a successful Agent execution.

After activation, every reply, final reply, progress operation, file delivery, and
control targets only canonical `delivery_channel_id`. Candidate-bearing Resources
never lower root-message provisioning coordinates into ordinary delivery payloads,
so current and old Agent Workers cannot call the legacy `ensure_thread()` path for
them. Legacy provisioning remains only for conversations created by old producers
without a candidate.

During mixed rollout, old Agent Workers receive no wake for a new gated Session until
current code records provider readiness. Application rollback leaves already gated
inputs and projection rows inert and unwoken; a forward deployment resumes the same
durable work. The additive schema remains installed throughout the compatibility
window.

Affected requirements: `title-260802/REQ-3`, `title-260802/REQ-4`,
`title-260802/REQ-6`.

Rejected alternatives:

- Execute immediately and defer every ordinary Channel Action delivery. This spreads
  new waiting and release semantics across replies, progress, files, finalization,
  action recovery, and old-Worker compatibility.
- Allow legacy `ensure_thread()` and reconstruct ownership later. This violates D3
  and cannot distinguish provider-owned threads after interruption.

### title-260802/ADR-D6 — Admission evidence permits non-blocking shared thread provisioning

D6 supersedes D5 in full. It also supersedes D3 and D4 only where they require
exclusive projection-owned POST authority and prohibit candidate-bearing ordinary
controls or legacy `ensure_thread()` from provisioning. D1 and D2, D3's conservative
provider ownership tests, and D4's separate projection-domain retry identity remain
authoritative.

Discord's existing synchronous history path performs an authenticated exact
trigger/root-message GET before the acceptance transaction. Extend that result with a
bounded credential-free root-thread observation: exact Guild, parent channel, root
message, observation identity and time, root flags, and either the exact validated
existing thread identity or a `thread_absent` fact. Inconsistent thread object and
`HAS_THREAD` evidence is unknown, never absent.

The candidate transaction records `thread_absent` only when the observation belongs
to the same current connection, exact parent/root and trigger, history or replay
boundary, Resource creation path, and first canonical input for the new Session and
Binding, and the Resource has no canonical delivery target. No Agent Worker, provider
control, or Channel Action can run before this transaction commits and dispatches
wake, so the durable absence observation precedes every Azents
provisioning-capable operation for that candidate.

Session and Binding creation, canonical mailbox admission, running transition, wake,
promotion, automatic Session title generation, and AgentRun remain immediate.
Existing joined-presence and progress controls and ordinary Channel Actions remain
independent and may call existing `ensure_thread()`. A current projection reconciler
may also run its D3 GET-first create path. Discord permits one thread for the root, so
racers converge by GET on the same provider thread and record the same canonical
Resource `delivery_channel_id`.

Direct current-code creation proof remains strongest: a projection-owned persisted
preflight and attempt plus a validated successful create response or GET
reconciliation proves the exact thread, active Bot owner, and exact stored
provisional name.

A thread created through ordinary delivery may be adopted without blocking execution
only when all of the following hold:

- the candidate has durable admission-time `thread_absent` evidence for the exact
  root;
- a later authenticated root GET returns one exact thread for the same
  Guild/parent/root relationship;
- canonical Resource `delivery_channel_id`, when present, is absent or equals that
  thread;
- `owner_id` is the currently connected Bot identity;
- thread metadata is complete and internally valid, including a valid provider
  creation timestamp;
- the current thread name exactly equals the candidate's stored provider-normalized
  provisional Agent title; and
- connection, route, Resource, creating Binding, Session, Agent, credential, and
  lifecycle authority remain current.

This is provider evidence, not inference from mutable Resource labels or delivery
status. If the admission observation already showed a thread, was unknown or
inconsistent, does not match the exact root, or any later owner, name, metadata, or
target check fails, the Resource may still record or reuse the usable thread as
canonical `delivery_channel_id`, but title ownership becomes
`unmanaged`/`relinquished`. Session execution and ordinary delivery continue, and no
rename is attempted.

Once adoption or direct proof records provider readiness, the existing
title-first/thread-first aggregate logic applies. The first winning automatic Session
title arms the projection atomically. The title reconciler GETs current state,
applies only while the name still equals the stored provisional name, and otherwise
relinquishes. Transient provisioning and title failures retry in projection state;
ordinary replies, progress, files, and `finish` retain their existing at-most-once
delivery semantics.

Current candidate-aware provisioning always uses the candidate's stored provisional
title rather than rereading a later Agent name. A truly legacy Worker still uses the
current Agent name. If the Agent is renamed between candidate admission and a legacy
create, name proof can differ and the projection deliberately relinquishes rather
than guessing. This is a conservative mixed-rollout false negative, not a fallback
mode; Session title, execution, and delivery remain correct.

Lifecycle revocation terminalizes projection work without changing the already
admitted input, AgentRun, or Session title. Archive, disconnect, decommission,
connection termination, and purge retain current ordinary delivery behavior and
additionally relinquish or delete projection state in restrictive order. Restore
never reactivates it.

Mixed rollout and rollback are structurally safe:

- old producers create no candidate and remain legacy;
- new producers create the candidate and admission evidence while leaving ordinary
  controls and wake unchanged;
- old or new Agent Workers may provision through `ensure_thread()` after wake;
- old Workers cannot falsify the prior exact-root absence or later provider
  owner/name/metadata evidence; and
- rollback leaves candidate rows inert while legacy execution and delivery continue;
  a forward deployment later adopts only a still-proven provisional thread or
  relinquishes it.

No new broker mode, feature flag, Redis authority, staged Worker floor, deferred file
claim, or provider-delivery outbox is introduced.

Affected requirements: `title-260802/REQ-3`, `title-260802/REQ-4`,
`title-260802/REQ-5`, `title-260802/REQ-6`.

Rejected alternatives:

- D5's execution gate violates confirmed non-blocking execution requirements.
- A separate candidate outbound outbox without a legacy Agent-Worker fence is
  internally incomplete; adding a staged Worker floor is broader than necessary.
- Per-action defer or rewrite rules spread a new protocol across controls, replies,
  progress, files, recovery, and broad legacy delivery readers.
- Capability-specific broker routing creates a second execution protocol across
  generic wake, recovery, handover, and rollback paths.
- Database trigger or row-level-security interception obscures canonical Action
  semantics and request-local Runtime file authority.
- Resource labels, Bot ownership alone, current Agent name, or incomplete provider
  metadata are insufficient ownership proof.

## Consequences

- Initial title projection gains a typed persistence root rather than extending
  Resource labels or generic Session-title state.
- The final automatic Session title and its eligible provider projections cannot be
  separated by a database crash window.
- The provider-attempt and recovery policy remains independently selectable.
- Recoverable Discord failure delays projection without requiring another invocation
  or Agent response.
- Retry remains bounded operationally by persisted due time and capped backoff and
  bounded semantically by current lifecycle authority rather than an arbitrary count.
- The existing creation-only rule in `binding-260731/ADR-D5` remains authoritative
  for Agent renames and pre-existing provider titles. This snapshot supersedes only
  its prohibition on a later rename for the one confirmed Azents-created thread's
  first final automatic Session title.
- Provider evidence, rather than local labels, determines whether the initial title
  lifecycle exists.
- Human-title preservation has a documented provider race window because Discord
  offers no conditional name update.
- Candidate-bearing Session admission, promotion, wake, title generation, and Agent
  execution remain immediate. Provider readiness delays only Discord provider
  mutation.
- Existing reply, progress, file, `finish`, mailbox, and wake semantics remain
  unchanged; only projection evidence and desired-state retries are added.
- More than one Azents path may race to create or reuse the provider thread, but only
  complete provider evidence creates title ownership.
- Mixed-version ambiguity sacrifices the one-time provider rename rather than user
  title safety or Agent execution.
