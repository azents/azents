---
title: "External Channel Session and Discord Thread Automatic Titles Design"
created: 2026-08-02
updated: 2026-08-02
tags: [external-channel, session, discord, slack, title, backend, testenv]
document_role: primary
document_type: design
snapshot_id: title-260802
---

# External Channel Session and Discord Thread Automatic Titles Design

- Snapshot: `title-260802`
- Document reference: `title-260802/DESIGN`
- Requirements: [`title-260802/REQ`](../requirements/title-260802-external-channel-automatic-title.md)
- Decisions: [`title-260802/ADR`](../adr/title-260802-external-channel-automatic-title.md)
- Mode: Autonomous
- Decision owner: dedicated read-only autonomous design interviewee

## Current Behavior and Requirement Gaps

Direct Session input already owns a two-phase automatic title lifecycle. Mailbox promotion converts the first eligible `user_message` into a deterministic `auto_initial` Session title and records the Event identity. The Worker schedules a best-effort lightweight-model call, and `SessionTitleService` replaces that value with `auto_generated` only while the same Event remains authoritative. Manual titles win, failures do not affect Agent execution, and the generated automatic title is at most 50 characters.

External Channel invocation batches instead promote contiguous `external_channel_message` Events. The exact human trigger already carries `authorization = authorized_invocation`; surrounding provider history carries `context_only`. The title helpers accept only `user_message`, so Slack- and Discord-created Sessions remain untitled even though the transcript contains an unambiguous user request. Merely generalizing the helper would also let a later invocation title a pre-existing untitled Session, so the new-Session creation boundary needs durable evidence.

For an isolated Discord root-message conversation, provider controls currently create or reuse the thread opportunistically inside ordinary message delivery. A newly created thread uses the routed Agent name. The provider call completes before a later transaction records the delivery thread, leaving no durable pre-POST provisional-name or ownership-attempt fence. Existing and mixed-version Workers also share the same provider-control claim predicate, so a legacy Worker could create the thread while omitting new ownership evidence.

Existing provider delivery attempts are durable at-most-once message/control mutations. Rate limits and provider rejection become terminal failures; transport and server ambiguity become terminal unknown outcomes. Discord thread provisioning and thread-name projection are readable desired state with provider reconciliation, so the title-aware paths require dedicated safe recovery without changing ordinary message-delivery semantics.

## Revision 2 Corrections

Revision 2 resolves the revision 1 audit findings:

- an armed automatic-title snapshot is immutable for the one provider projection and is not cancelled by a later manual Session-title edit;
- provisional title and title-aware provisioning identity are persisted before provider mutation, with stale/crash reconciliation;
- candidate-bearing provisioning uses a durable origin/operation fence that legacy Worker predicates cannot claim;
- first eligible External Channel title input is proven by a new-Session candidate instead of inferred from `title_source = null`; and
- qualifying artifacts are created from every production Session/Binding creation path, including access-approved creation.

## Revision 4 Correction

Revision 4 rejects revision 3's provider-readiness execution gate because it
contradicted the confirmed non-blocking execution contract. Candidate-bearing
Discord admission commits, marks running, and wakes the Session exactly as today.

The existing authenticated exact-root history GET now contributes durable
admission-time thread absence evidence. Existing ordinary controls, Channel Actions,
and `ensure_thread()` remain non-blocking and may provision concurrently with the
projection reconciler. A thread receives title ownership only when direct
projection-owned creation proof or the complete D6 admission-evidence adoption proof
matches. Ambiguity relinquishes only the provider rename.

## Revision 5 Correction

Revision 5 removes the revision 4 dependency on a retained mailbox row. Mailbox
promotion deletes the source row after creating Events, so it cannot be durable
projection authority. The persistent Session-title candidate instead owns exact
creation provenance: Session, creating Binding, trigger provider-message key, and
consumed Event identity. The Discord projection references that candidate and the
admission observation; mailbox identity remains transaction-local input only.

## Requirement and Decision Traceability

| Requirement | Accepted decisions | Design mechanisms |
| --- | --- | --- |
| `title-260802/REQ-1` | Fixed by Requirements | M1 durable new-Session title candidate and authorized Event extraction |
| `title-260802/REQ-2` | D1 | M1 title source, M3 atomic final-title arming |
| `title-260802/REQ-3` | D1, D3, D4, D6 | M2 projection candidate and admission observation, M4 direct/adopted provider proof |
| `title-260802/REQ-4` | D1, D2, D3, D4, D6 | M2 aggregate, M3 immutable snapshot, M4 ownership proof, M5 reconciler |
| `title-260802/REQ-5` | D2, D3, D6 | M4 exact provider proof, M6 one-time provider takeover fence, M8 no backfill |
| `title-260802/REQ-6` | D1, D2, D3, D4, D6 | M3 atomic handoff, M4 durable proof/recovery, M5 Worker reconciliation, M8 mixed-version conservative adoption |
| `title-260802/REQ-7` | Fixed by Requirements | M7 provider-compatible normalization |

## Architecture and Ownership

### Session title authority

`agent_sessions.title`, `title_source`, `title_generated_at`, and `title_generation_event_id` remain the only Session-title authority. External Channel state never becomes a second Session-title source and never changes a Session title from provider state.

The title-source helper becomes a closed user-like extractor:

- `user_message` retains current text and file-part behavior;
- `external_channel_message` yields a source only when it is human-authored and `authorization = authorized_invocation`;
- its body is supplemented with bounded file names and media types already present in canonical attachment metadata; and
- `context_only`, Bot-authored, Agent-authored, and tool-result Events yield no source.

An External Channel Event additionally requires one durable new-Session title candidate. Helper eligibility alone is insufficient.

### Durable External Channel Session-title candidate

Add `external_channel_session_title_candidates`, one row for each newly created External Channel AgentSession that is entitled to exactly one creation-boundary automatic title.

The candidate immutably retains:

- `agent_session_id`, unique;
- the creating `binding_id`;
- the exact `trigger_provider_message_key` from the invocation that created the Session;
- `status`: `pending`, `consumed`, or `relinquished`;
- the consumed `event_id`, when present; and
- timestamps and a bounded terminal reason.

Existing Sessions and Bindings receive no backfill candidate. A later Binding receives no candidate because it did not create the Session.

When mailbox promotion inserts Events, the title-assignment transaction locks a pending candidate and verifies that the inserted External Channel Event belongs to the candidate Session, creating Binding, and exact trigger provider-message key. Only then may it set `auto_initial` and atomically mark the candidate consumed with the Event ID. A manual or otherwise pre-existing title relinquishes the candidate. An empty unusable source consumes or relinquishes it without creating a title.

The candidate makes the External Channel behavior explicitly one creation-boundary title. Clearing a title later does not manufacture another first external invocation. Existing direct-Session clear/reset behavior remains unchanged because direct `user_message` eligibility does not use this candidate.

### Central creation boundary

Both production paths that can create an External Channel root Session and Binding
use one idempotent artifact service:

1. ordinary shared-ingestion Binding creation records every artifact during the
   first canonical acceptance; and
2. `ExternalChannelAccessService.allow()` may create the root Session and Binding
   before replay, so the later exact access-request replay attaches the candidate and
   projection to that same Binding/Session even though the local replay path reports
   `session_created = false`.

The service accepts exact creation provenance: Session, Binding, Resource, access
request when applicable, trigger provider-message key, and the Discord admission
observation. It creates the Session-title candidate only for the root Session created
for that trigger. For a qualifying Discord root-message Resource, it also creates the
projection referencing that durable candidate and its provisioning control. A retry
with another Session, Binding, trigger, Resource, Agent, provisional title,
observation, or candidate identity is incompatible.

Tests and absence verification cover every `create_root_session(... start_reason=external_channel)` plus `create_binding_idempotent()` production path so a future path cannot silently omit these artifacts.

Canonical mailbox admission, provider-control intents, conversation-position
advance, Session running transition, and post-commit wake remain unchanged and commit
without waiting for projection readiness.

### Discord admission-time root observation

Discord synchronous history already performs an authenticated GET for the exact
trigger/root message before acceptance. Extend the provider-neutral history result
with a bounded credential-free Discord observation containing:

- connection, Guild, parent-channel, root-message, trigger, and observation identity;
- provider observation time and exact root flags;
- status `thread_absent`, `thread_present`, or `unknown`; and
- for `thread_present`, validated thread ID and parent/root relationship.

`thread_absent` is valid only when the response contains no thread object and its
flags do not indicate a thread. Inconsistent flags, malformed or incomplete thread
metadata, transport ambiguity, or identity mismatch yields `unknown`, never absence.

The acceptance transaction persists the observation only when it matches the current
connection, exact trigger and replay boundary, target Resource, creating
Binding/Session, first canonical mailbox input, and a Resource with no canonical
delivery target. Because wake follows that commit, the recorded absence precedes
every Azents provisioning-capable control or Channel Action for the candidate.

### Discord initial-title projection authority

Add one dedicated Discord initial-title projection aggregate per qualifying External Channel Resource. It is the sole authority for whether one thread owns a one-time initial Session-title projection.

The aggregate immutably references:

- the External Channel Resource;
- the creating Binding;
- the AgentSession created for that Binding; and
- the fenced provisioning control identity; and
- the durable Session-title candidate plus exact admission-time root observation.

A unique Resource constraint prevents another Binding from creating a second initial-title lifecycle.

### Persistence model

Add `external_channel_discord_thread_title_projections` with two independently recoverable phases.

| Field | Purpose |
| --- | --- |
| `id` | Durable projection and control identity |
| `resource_id` | Unique Discord Resource ownership root |
| `binding_id` | Immutable creating Binding |
| `agent_session_id` | Immutable Session title source |
| `session_title_candidate_id` | Durable unique creation provenance owning Session, Binding, exact trigger, and consumed Event identity |
| `provisioning_protocol_version` | Projection-domain control identity understood only by current provisioning code |
| `requested_provisional_title` | Exact normalized Agent-derived name, stored before provider mutation |
| admission observation fields | Exact Guild/parent/root/trigger identity, observed time, root flags, and `thread_absent` / `thread_present` / `unknown` evidence |
| `provisioning_status` | `pending`, `attempting`, `retry_wait`, `ready`, `unmanaged`, or `failed` |
| `preflight_absent_at` | Durable proof that the last fenced create attempt observed no thread before POST |
| `thread_channel_id` | Provider-confirmed immutable ownership thread identity |
| `expected_provisional_title` | Exact provider-confirmed title used by later takeover comparison |
| `desired_title` | Immutable snapshot of the first winning final automatic Session title |
| `title_generation_event_id` | Exact automatic-title Event fence captured at arming |
| `title_status` | `waiting`, `pending`, `attempting`, `retry_wait`, `applied`, `relinquished`, or `failed` |
| `provision_attempt_count` / `title_attempt_count` | Persisted reconciliation counts |
| `provision_next_attempt_at` / `title_next_attempt_at` | Due times for retry phases |
| `provision_claimed_at` / `title_claimed_at` | Worker claim times for stale recovery |
| phase failure fields | Sanitized retry or terminal diagnostics |
| `completed_at` fields | Terminal transition evidence for each phase |
| `created_at` / `updated_at` | Audit timestamps |

The projection row itself is the title-aware provisioning control. Its table and
protocol version are the durable identity; no new enum value or fenced row is inserted
into `external_channel_delivery_attempts`. Current ingress/provider-control
orchestration carries a typed projection-control reference when immediate attempt is
useful, and the current Worker drain queries the projection repository directly.
Legacy Workers do not query the new table and cannot claim, deserialize, settle, or
terminalize its rows. Ordinary at-most-once delivery semantics and every existing
delivery enum remain unchanged.

Database constraints enforce:

- one projection/control per Resource;
- immutable creating Binding and Session identity;
- immutable candidate identity whose Session, creating Binding, and trigger match the
  projection;
- non-empty requested provisional title from candidate creation;
- internally consistent admission observation identity and status;
- `thread_absent` requiring matching root flags and no existing thread identity;
- provider readiness fields appearing together;
- title readiness fields appearing together;
- title retry states requiring provider and title readiness;
- retry states requiring their next-attempt timestamps;
- terminal phase states requiring completion timestamps; and
- `ready` provider identity exactly matching the Resource's canonical
  `delivery_channel_id` whenever the provider target is loaded or mutated.

The Resource remains the canonical current provider conversation/delivery target. The projection's thread ID is immutable ownership evidence. Repository claim and settlement reject any mismatch; neither value may be selected as a fallback for the other.

## Transactional Session-Title Convergence

### Initial automatic title

The mailbox promotion transaction appends the authorized external Event, locks the matching Session-title candidate, derives the source, and calls the existing `set_initial_auto_title_if_unset()` fence. A successful update and candidate `pending -> consumed` transition commit together with the Event. If the Event is later than the candidate trigger, belongs to another Binding, or the candidate is absent/consumed, no External Channel automatic title is initialized.

### Final automatic title and immutable arming

`SessionTitleService.generate_from_initial_prompt()` continues model I/O outside a database transaction. When a title is available, one short transaction:

1. performs the existing fenced `auto_initial -> auto_generated` replacement;
2. only when that replacement succeeds, finds nonterminal Discord projections owned by the same Session and consumed generation Event;
3. snapshots the exact generated title and Event identity into each projection; and
4. moves each provider-ready projection to title `pending` with an immediate due time.

The Session title and projection snapshots commit atomically. Once armed, the projection's `desired_title` and Event identity remain authoritative for that one Discord operation even if a user later manually edits or clears the Session title. The manual value is never propagated and never replaces the captured desired title. Session archive, Binding/Resource/route/Agent/connection revocation, or provider title takeover can still terminate projection authority.

This preserves D1's snapshot while keeping Session and provider titles independent after the one-time operation.

## Shared Discord Thread Provisioning and Provider Proof

### Control creation

For a candidate-bearing Discord Resource, the central creation boundary stores the
exact normalized `requested_provisional_title`, creates the versioned projection
control, and retains the exact admission observation in the same transaction as the
ordinary mailbox input and initial provider controls.

Old producers create neither candidate nor projection control and retain the legacy
flow. Existing provider controls and Channel Actions remain independent and may call
`ensure_thread()` before or concurrently with the projection reconciler.

### Current Worker ownership

The existing Worker process adds a dedicated due-provisioning query over the new
projection table. Legacy Worker code has no model or query for that table.
Compatibility tests run the actual legacy binding-wide delivery readers and lifecycle
queries and prove that projection state creates no unknown enum-bearing row in their
tables.

For a claimed projection, the current Worker revalidates projection-control version,
Resource, creating Binding, durable title candidate, Session, Agent, route,
connection, credential, Bot identity, and provider root-message authority.

### Direct projection-owned proof

Provisioning performs the accepted D3 proof with a durable mutation fence:

1. GET the root message.
2. If a thread already exists, evaluate the admission-evidence adoption proof below;
   adopt it when every proof field matches, otherwise record its usable delivery
   identity as `unmanaged` and never arm provider title ownership.
3. If no thread exists, open a short transaction that revalidates the claim and provider authority, increments the provisioning generation/attempt, and persists `preflight_absent_at` plus the exact already-stored requested provisional title before POST.
4. POST thread creation immediately after that commit.
5. A valid success response proves ownership.
6. A transport, server, response, cancellation, or process ambiguity is reconciled by GET.
7. Reconciliation proves ownership only when the returned thread owner is the active connected Bot and the name exactly equals `requested_provisional_title`.
8. If reconciliation still cannot conclude, persist `retry_wait`. The next attempt GETs first: a matching Bot-owned thread proves the prior POST; absence permits another POST only after another durable preflight-absence fence; different ownership/name becomes unmanaged.

A crash before POST leaves durable absence/attempt evidence and safely resumes with GET. A crash after provider commit but before database readiness also resumes with GET and bounded provider proof.

Current candidate-aware provisioning always POSTs the exact stored
`requested_provisional_title`; it never rereads a later Agent name.

### Admission-evidence adoption proof

An ordinary legacy or current provider control may win thread creation first. A later
projection GET may adopt that thread only when:

- the projection retains `thread_absent` for the exact admission root;
- the authenticated root GET returns one exact thread with matching
  Guild/parent/root identity;
- Resource `delivery_channel_id` is absent or equals that thread;
- `owner_id` equals the active connected Bot;
- current name equals `requested_provisional_title`;
- thread metadata is complete and internally valid, including its provider creation
  timestamp; and
- the complete connection, route, Resource, creating Binding, Session, Agent,
  credential, and lifecycle authority remains current.

An admission observation that was present, unknown, inconsistent, or mismatched can
never authorize adoption. Bot ownership, Resource labels, delivery status, or current
Agent name alone are insufficient.

### Provider readiness transaction

Once a usable thread is known, one transaction:

- locks projection, Resource, creating Binding, durable title candidate, Session,
  route, Agent, and connection;
- writes or verifies the Resource `delivery_channel_id`;
- for direct or adopted Azents ownership, writes projection `thread_channel_id`,
  `expected_provisional_title`, proof kind, and `provisioning_status = ready`;
- for a pre-existing or insufficiently proven thread, records its usable canonical
  target, sets `provisioning_status = unmanaged`, and sets title `relinquished`;
- requires Resource and projection thread identities to match when ownership is
  ready;
- terminalizes the projection-domain provisioning phase; and
- makes an already armed owned projection title-pending.

Known permanent provisioning failure marks the projection provisioning phase failed,
while transient outcomes schedule projection-owned retry. Neither outcome changes
mailbox, wake, AgentRun, ordinary delivery, or Session-title state.

### Ordinary outbound delivery boundary

Initial controls and every ordinary reply, final reply, progress update, and file
delivery retain existing at-most-once semantics. Before a canonical target exists,
their Discord payload may carry the existing root provisioning coordinates and call
`ensure_thread()`. After any path records `delivery_channel_id`, later payloads target
that canonical thread.

Current candidate-aware delivery passes the stored provisional title to
`ensure_thread()` instead of the current Agent name. A truly legacy Worker may use a
later Agent name. If the names differ, the thread remains usable for delivery but the
projection conservatively relinquishes title ownership.

Discord's single root-thread relationship and Resource target recording make
concurrent projection/control creation converge on one thread. Only the direct or
adoption provider-proof rules establish title ownership.

## Desired-State Thread-Title Reconciliation

The existing Worker extends the same External Channel control loop with a bounded due-title query. No new process, queue, Redis dependency, feature flag, configuration, or runtime mode is added.

### Claim and authority validation

PostgreSQL row locking with skip-locked semantics claims due title `pending` or `retry_wait` rows and recovers stale `attempting` rows. The claim validates:

- projection identity and armed nonterminal state;
- exact Resource, creating Binding, and AgentSession relationship;
- connected Binding;
- active Resource, AgentSession, and Agent;
- current route ownership and non-disconnected connection;
- configured Discord credentials, tenant, and Bot identity;
- exact equality between canonical Resource `delivery_channel_id` and immutable projection `thread_channel_id`; and
- complete provider and desired-title readiness.

It deliberately does not require current Session `title`, `title_source`, or `title_generation_event_id` to remain equal after arming. The immutable projection snapshot owns this one operation. Secrets are operation-scoped and never copied into projection state, logs, events, or test evidence.

### Provider convergence

For one claimed projection the provider client performs adjacent operations:

1. GET the current thread channel.
2. Validate exact thread and parent/provider ownership boundaries.
3. If its name equals `desired_title`, settle `applied` without PATCH.
4. If its name differs from `expected_provisional_title`, settle `relinquished` without PATCH.
5. Otherwise immediately PATCH only `name` to `desired_title`.
6. Validate success or persist retry for later GET reconciliation.

No unrelated database or provider work occurs between the matching GET and PATCH. Discord exposes no atomic conditional name update, so a human rename in that interval may be overwritten. A successful projection is terminal and Azents performs no later synchronization; a later human rename remains authoritative.

### Retry and terminal outcomes

Both provisioning and title phases use persisted exponential backoff capped at bounded local constants. There is no attempt-count exhaustion while the relevant complete lifecycle authority remains current.

| Outcome | Result |
| --- | --- |
| Thread/title already equals desired | phase succeeds without duplicate mutation |
| Title differs from expected provisional | title `relinquished` |
| Admission showed an existing/unknown thread or adoption proof is incomplete | provisioning `unmanaged`, title `relinquished`, ordinary delivery continues to the preserved usable thread |
| Binding, Session, Agent, route, Resource, connection, credential, or provider authority revoked | nonterminal phase relinquishes or fails before provider mutation |
| Target deleted, credentials rejected, permission denied, malformed target, or confirmed permanent rejection | phase `failed` or `relinquished` according to authority ownership |
| Rate limit, provider server error, transport failure, cancellation, process interruption, or ambiguous outcome | phase `retry_wait` |

Worker shutdown or crash leaves a durable claim; stale recovery returns it to retry. Every retry begins with GET, so a prior successful ambiguous create or PATCH is recognized before another mutation.

## Provider-Compatible Titles

The existing automatic title generator returns at most 50 normalized characters, below Discord's thread-name maximum. A valid final automatic title therefore requires no normal shortening or semantic rewrite.

One shared deterministic provider normalizer:

- collapses whitespace consistently;
- retains language and content;
- truncates only if the provider bound is exceeded, preserving a non-empty prefix; and
- rejects an empty result without changing Session or provider state.

The exact normalized provisional title is stored before provisioning and reused byte-for-byte for ownership proof and later title-takeover comparison. Later Agent renames never change it.

## Security and Permissions

- Discord Bot tokens remain encrypted at rest and operation-scoped in memory.
- The active connection's provider Bot user ID is required for ambiguous-create proof.
- Provider reads and writes are limited to the root/thread identities owned by the projection Resource.
- Both phases revalidate Workspace, Agent, Session, route, Binding, Resource, connection, credential, and provider identity boundaries.
- No External Channel principal becomes an Azents execution User through title generation or projection.
- Provider bodies, credentials, raw exceptions, callback data, source message text, and generated titles are not logged. Logs retain identifiers, state transitions, attempt counts, and sanitized failure codes.
- No public API grants provider rename or provisioning authority.

## Migration, Rollout, and Rollback

The additive migration creates:

- the External Channel Session-title candidate table and status enum;
- the versioned Discord thread-title projection/control table and phase enums;
- constraints, indexes, and foreign keys; and
- no backfill rows.

Existing Sessions, Bindings, Resources, and threads remain unmanaged. Old producers continue their existing path and create no candidate. New producers use the fenced path structurally whenever they create a qualifying projection candidate.

### Rollout

1. Apply the additive candidate and projection schema before deploying candidate producers.
2. Deploy current binaries in any rolling order after schema availability.
3. Old Worker predicates ignore projection rows but retain existing ordinary
   `ensure_thread()` behavior after the unchanged Session wake.
4. Current Workers process projection controls and may race ordinary controls. Both
   converge on Discord's one root thread and the Resource's canonical target.
5. Direct proof or the complete admission-evidence adoption proof creates title
   ownership. Incomplete evidence conservatively relinquishes only the rename.

Compatibility tests execute actual legacy provider-control, binding-management,
lifecycle, and purge delivery queries and prove that candidate provisioning creates
no row for them to deserialize or mutate. Old-Worker simulations prove that ordinary
thread creation after durable admission absence can be adopted only with exact
provider owner, name, root, target, and metadata evidence.

### Rollback

Application rollback does not remove or reinterpret the additive schema. Old
producers resume legacy behavior and create no candidates. Existing projection rows
remain inert while Session execution and ordinary provider delivery continue through
the legacy paths.

A later forward deployment resumes exact projection rows, revalidates lifecycle
authority, and either adopts a still-proven provisional thread, continues GET-first
provisioning, or relinquishes. Revoked authority terminalizes safely before mutation.
Database removal is outside ordinary application rollback and cannot occur while
projection rows remain nonterminal.

No public API, OpenAPI document, generated client, Web route, UI state, Helm value, environment variable, Discord command, or provider scope migration is required.

## Observability and Operations

The provider-control drain reports bounded counts for provision claims, title claims, ready/unmanaged/applied/relinquished/failed transitions, retries, and stale recoveries. Structured logs identify projection, Resource, Binding, Session, control, attempt, prior/new status, and sanitized provider category without title content.

Operational diagnosis distinguishes:

- waiting for the matching first external Event;
- provisioning pending, preflight-fenced, or retrying;
- provider-ready but waiting for final automatic title;
- title retry;
- pre-existing or human/provider takeover;
- lifecycle revocation;
- permanent provider failure; and
- successful convergence.

A growing provisioning- or title-retry population indicates delayed provider
projection work. It does not block Session execution or change ordinary
at-most-once delivery outcomes. No new alert threshold is introduced.

## Test Strategy

### E2E primary verification matrix

| Journey | Required evidence |
| --- | --- |
| New Discord root invocation | Exact-root history records durable thread absence before acceptance; the Session wakes immediately, reaches `auto_generated`, and direct or adopted provider proof permits one final title PATCH |
| Context exclusion and attachments | Title fixture receives only authorized body plus safe file metadata; `context_only` and Bot content are absent |
| Access-approved creation | Access Allow creates the same title/projection artifacts; replay consumes the exact candidate and reaches the same provider result |
| Existing or later Session invocation | A pre-existing Session without a new candidate remains untitled; later External Channel Events cannot create eligibility |
| Manual edit after arming | `AUTO_GENERATED` arms the projection, a manual edit/clear follows before provider application, and the immutable captured automatic title is still applied once; manual text is never sent to Discord |
| Pre-existing Discord thread | Admission observation records the existing thread, ordinary execution/delivery continues, projection becomes unmanaged, and zero title PATCH operations occur |
| Human takeover before title PATCH | Fake provider changes the provisional name; title projection relinquishes and performs zero PATCH operations |
| Crash after preflight before POST | Stale recovery GETs first, proves absence, safely retries provisioning, and completes without another invocation |
| Crash after committed POST before DB readiness | Recovery GET proves Bot owner and exact provisional name, atomically records Resource/projection readiness, and continues |
| Agent output races provisioning | Session wake and AgentRun proceed immediately; ordinary control or Channel Action may win `ensure_thread()`, and the projection adopts only with exact admission/root/Bot/name/metadata proof |
| Agent rename during mixed rollout | A legacy Worker creates with the later Agent name; delivery remains usable but the stored provisional-name mismatch relinquishes title ownership |
| Recoverable PATCH failure | Rate limit/server/transport ambiguity persists retry; no new invocation occurs; GET reconciliation reaches applied |
| Lifecycle revocation | Disconnect/archive before a due phase prevents later provider mutation and terminalizes safely |
| Mixed-version coexistence | Old Workers ignore projection rows, may provision after the unchanged wake, cannot falsify prior root absence, and produce either exact provider-backed adoption or conservative relinquishment |
| Slack new Session | Exact first trigger consumes the general title candidate and reaches automatic title with no Discord projection |

### E2E plan and fixtures

Extend the deterministic Discord provider fake with exact-root flags and thread
objects containing ID, parent/root relationship, owner ID, name, and
`thread_metadata.create_timestamp`; direct GET/PATCH channel endpoints; controlled
create/read/PATCH sequences; preflight and mutation barriers; state mutation for
human takeover; request counters; and sanitized final-name evidence.

Add deterministic AI mock fixtures for the external authorized-message title prompt and response. The primary journey runs through real Gateway ingress, setup/access selection, Session and Binding creation, fenced provisioning, mailbox promotion, title generation, title reconciliation, and fake Discord PATCH.

The fake is required because live Discord cannot provide deterministic CI evidence
for response loss, admission-observation consistency, old/new provisioning races,
rate limits, Agent rename, or human takeover.

### Lower-level verification

Backend tests cover:

- candidate creation from both production Session/Binding creation paths;
- exact Session/Binding/trigger Event candidate consumption and later-Event exclusion;
- authorized/context/Bot/body/file title extraction;
- projection uniqueness, immutable ownership, provisional title and exact-root
  observation persistence, both readiness orders, and atomic arming;
- projection-domain control absence from actual legacy delivery readers and current special dispatch;
- exact-root flag/thread consistency, direct preflight persistence, stale recovery
  before/after POST, provider ownership proof, and Resource/projection identity
  equality;
- unchanged immediate mailbox enqueue, Session running transition, wake, initial
  controls, and Channel Action availability before provider readiness;
- candidate-aware current provisioning using the stored provisional title;
- old-Worker `ensure_thread()` adoption with exact root/Bot/name/metadata evidence,
  plus Agent-name mismatch and incomplete-evidence relinquishment;
- title GET/PATCH reconciliation, immutable armed snapshot after manual edits, provider errors, and lifecycle revocation;
- multi-Binding isolation and later-Binding non-inheritance; and
- Worker cancellation, restart, retry scheduling, and capped backoff.

The Discord fake's own tests cover new endpoints, owner/name state, scenarios, barriers, and sanitized evidence.

### CI policy and evidence

Deterministic unit/integration tests and fake-provider E2E journeys are required CI checks and fail rather than skip when local prerequisites are present. No live Discord test is required. Optional live validation may skip only for absent credentials and cannot replace deterministic evidence.

Evidence consists of pytest results plus sanitized fake-provider request counts, ownership fields, state transitions, and final thread names asserted by E2E tests. Testenv changes are required because provider crash and mixed-version contracts cannot be proven with backend mocks alone.

## Requirement-Level Feasibility

| Requirement | Status | Repository evidence |
| --- | --- | --- |
| `REQ-1` | feasible | Both root-Session creation paths expose root-created, Binding, and exact trigger identity; canonical Events retain binding/provider message identity for durable candidate consumption |
| `REQ-2` | feasible | Existing title repository fences and `SessionTitleService` accept a generalized source without changing manual precedence or model-call timing |
| `REQ-3` | feasible | Existing exact-root history GET, immediate admission/wake, ordinary `ensure_thread()`, provider Bot identity, and the projection reconciler support non-blocking shared provisioning with a stored provisional title |
| `REQ-4` | feasible | Shared PostgreSQL transactions atomically capture final title and direct/adopted provider proof; Discord's one root thread and exact admission absence allow current or legacy creation to converge |
| `REQ-5` | conditional | GET-before-PATCH preserves observed takeover, but Discord lacks atomic compare-and-set; D3 explicitly accepts the residual race |
| `REQ-6` | feasible | Admission observation, projection-domain desired-state retry, immediate unchanged wake, and conservative mixed-version adoption preserve execution independence across provider/DB interruption |
| `REQ-7` | feasible | Automatic titles are capped below Discord's bound and the existing provider helper supplies deterministic normalization |

No repository feasibility blocker remains. The sole conditional result is the accepted Discord GET/PATCH race.

## Authority Audit

Forward audit:

- `REQ-1` is covered by the durable new-Session title candidate and closed authorized-event extractor.
- `REQ-2` retains existing Session title authority and adds only the D1 atomic provider snapshot.
- `REQ-3` is covered by pre-provider provisional persistence, exact-root admission
  observation, and D3/D4/D6 shared provisioning proof.
- `REQ-4` is covered by the per-Resource aggregate, immutable arming, proof,
  direct/adopted readiness, and reconciler.
- `REQ-5` is covered by pre-existing-thread exclusion, expected-name takeover, and terminal one-time behavior.
- `REQ-6` is covered by unchanged immediate admission/wake, system-owned projection
  controls, persisted retries, conservative adoption, and full lifecycle validation.
- `REQ-7` is covered by provider-bound deterministic normalization.

Reverse audit:

- every material mechanism M1 through M8 cites confirmed Requirements, accepted ADR decisions, or unchanged current architecture;
- the External Channel title candidate does not become a Session-title source; it only authorizes one existing repository transition;
- Resource delivery identity remains canonical, while projection identity is immutable evidence checked for equality rather than a fallback target;
- the projection table is a protocol boundary invisible to legacy readers, while
  ordinary provisioning remains unchanged;
- armed desired title is immutable under D1 and no later manual title creates provider behavior;
- no API, frontend, Redis, Agent-tool, optional fallback, or second runtime mode is introduced; and
- every removal has replacement authority and an absence-verification method.

## Assumptions and Non-Blocking Risks

- Discord continues exposing root thread identity, owner identity, and current name.
- An active thread created by the connected Bot remains editable under current permissions. Permission loss terminalizes provider work without affecting Session title.
- Model title generation remains best-effort. If no final title wins, provider-ready projection stays title-waiting and the thread retains its provisional name until lifecycle revocation.
- A human can rename during the final GET/PATCH interval. This accepted provider limitation is minimized but not eliminated.
- Authority-bounded retry can retain rows during a long outage. Capped backoff and bounded batches prevent hot loops.
- A legacy Worker may create a candidate thread with a later Agent name during mixed
  rollout. The mismatch conservatively relinquishes provider title ownership while
  preserving Session execution and delivery.

## Design Authority

- Design revision: `5`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | A durable new-Session candidate authorizes exactly one External Channel trigger Event to enter the existing automatic title lifecycle | `title-260802/REQ-1`, `title-260802/REQ-2` | `required` |
| M2 | One per-Resource Discord projection aggregate owns immutable creating Binding/Session/candidate identity, provisional request, exact admission-time root observation, and the projection-domain provisioning control | `title-260802/ADR-D1`, `title-260802/ADR-D4`, `title-260802/ADR-D6`, `title-260802/REQ-3`, `title-260802/REQ-4` | `decided` |
| M3 | The winning final automatic Session title atomically arms an immutable desired-title/Event snapshot in every eligible projection | `title-260802/ADR-D1`, `title-260802/REQ-2`, `title-260802/REQ-4`, `title-260802/REQ-6` | `decided` |
| M4 | Direct projection-owned proof or exact admission-absence/root/Bot/name/metadata adoption establishes provider readiness while ordinary execution and provisioning remain non-blocking | `title-260802/ADR-D3`, `title-260802/ADR-D4`, `title-260802/ADR-D6`, `title-260802/REQ-3`, `title-260802/REQ-5`, `title-260802/REQ-6` | `decided` |
| M5 | The existing Worker runs authority-bounded GET-first provisioning and title reconcilers with persisted due time and stale recovery alongside unchanged ordinary at-most-once delivery | `title-260802/ADR-D2`, `title-260802/ADR-D4`, `title-260802/ADR-D6`, `title-260802/REQ-4`, `title-260802/REQ-6` | `decided` |
| M6 | Provider-name takeover or lifecycle revocation terminalizes the one-time operation; an armed automatic-title snapshot is not cancelled or replaced by later Session-title edits | `title-260802/ADR-D1`, `title-260802/ADR-D2`, `title-260802/ADR-D3`, `title-260802/REQ-4`, `title-260802/REQ-5` | `derived` |
| M7 | Provider normalization preserves valid automatic title semantics and only enforces deterministic Discord bounds | `title-260802/REQ-7`, current automatic-title and Discord provider constraints | `required` |
| M8 | Additive no-backfill rollout keeps projection state invisible to legacy readers, preserves immediate wake/delivery, and uses provider evidence with conservative relinquishment across mixed versions and rollback | `title-260802/ADR-D4`, `title-260802/ADR-D6`, `title-260802/REQ-4`, `title-260802/REQ-5`, `title-260802/REQ-6` | `decided` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| `USER_MESSAGE`-only title-source assumption and `title_source = null` as sufficient external eligibility | `title-260802/REQ-1` | M1 durable new-Session candidate plus closed event extractor | Title helper, mailbox promotion, repositories, tests | Existing external Sessions/later Events remain ineligible; both creation paths and exact trigger consumption are tested |
| Independent Session/Binding creation paths without shared title artifacts | M1/M2 authority | Central new-Session artifact boundary invoked by ingestion and access Allow | External Channel creation services/repositories | Grep-based production call-site audit and tests prove every root-created Binding path invokes it |
| Treating any legacy `ensure_thread()` success or Resource label as title ownership | `title-260802/ADR-D3`, `title-260802/ADR-D6` | M2/M4 direct proof or exact admission-absence/root/Bot/name/metadata adoption; ordinary provisioning remains | Discord history, delivery client, projection service, repository | Old/new race tests prove exact adoption and conservative relinquishment; labels or incomplete metadata never arm title ownership |
| Projection-owned provider call followed by unfenced delivery-channel recording | `title-260802/REQ-6`, `title-260802/ADR-D3` | M4 persisted provisional/preflight attempt and atomic Resource/projection readiness | Discord client, projection service, repository | Crash tests cover before POST and after committed POST before DB readiness |
| Resource labels as possible ownership inference | `title-260802/ADR-D1`, `title-260802/ADR-D3` | Projection provider proof; Resource remains current target with mandatory equality | Repository claims and service validation | Tests fail on identity mismatch and prove no ownership reconstruction from labels |
| Creation-only rule for confirmed Azents-created Discord threads | `title-260802/REQ-4`, D1-D3 | One immutable final automatic-title projection; Agent rename and existing-thread preservation remain from `binding-260731/ADR-D5` | Discord title behavior and Specs | E2E proves one eligible rename and zero rename for existing/later provider title paths |
| Existing at-most-once ledger as the only provider mutation recovery shape | `title-260802/ADR-D2`, `title-260802/ADR-D4` | Ordinary messages retain at-most-once semantics; projection aggregate owns safe provisioning/title retries | Projection dispatch and drain | Ordinary operations' tests remain unchanged; provisioning/title retry creates no chain or unknown enum row in legacy delivery tables |
| Arbitrary mixed rollout reliance on local labels or exclusive Worker ownership | `title-260802/ADR-D4`, `title-260802/ADR-D6` | M8 projection-domain isolation plus exact provider-evidence adoption or relinquishment | Migration, Discord history/result parsing, projection queries, rollout tests | Actual legacy delivery readers ignore projection rows; old-Worker create, Agent-rename mismatch, rollback, and forward resume tests pass |
| Discord fake without mutable thread-name/owner and crash barriers | Test Strategy under M4/M5/M8 | Deterministic provider proof, retry, takeover, and mixed-version evidence | Testenv fake and contract tests | Fake contract plus product E2E tests pass |
| Public APIs, clients, frontend, Slack provider mutation, Helm/config | None after repository-grounded analysis | Existing behavior remains authoritative | No change | Diff and generated-surface checks show no modification |

## Design Approval

- Mode: Autonomous
- Decision owner: dedicated read-only autonomous design interviewee
- Approved on: 2026-08-02
- Approved Design revision: `5`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`

The approved material scope is:

- one durable creation-boundary candidate authorizes the exact first External
  Channel trigger Event to enter the existing automatic Session-title lifecycle;
- one per-Resource Discord projection references that durable candidate and owns
  provisional-title, admission-observation, provider-readiness, immutable final-title,
  retry, and terminal state;
- immediate Session admission, mailbox promotion, wake, Agent execution, initial
  controls, and ordinary Channel Actions remain independent from provider readiness;
- direct projection creation proof or complete
  admission-absence/root/Bot/name/metadata evidence may establish one-time Discord
  title ownership;
- the existing Worker owns authority-bounded GET-first provisioning and title
  reconciliation with persisted retry and stale recovery;
- human/provider title takeover and lifecycle revocation terminalize provider
  projection without changing the Session title or admitted execution;
- additive no-backfill rollout and rollback preserve legacy execution and delivery
  while incomplete mixed-version evidence conservatively relinquishes only the
  optional provider rename; and
- provider normalization preserves valid automatic-title semantics and applies only
  deterministic Discord bounds.

The bidirectional authority audit and repository feasibility validation pass for this
revision. `REQ-5` remains conditional only on the accepted Discord limitation that a
human rename can race between the final GET and PATCH because Discord provides no
atomic compare-and-set operation.
