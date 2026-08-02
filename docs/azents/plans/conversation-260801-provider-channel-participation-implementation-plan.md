---
title: "Provider Channel Participation Settings Implementation Plan"
created: 2026-08-01
tags: [external-channel, slack, discord, conversation, backend, frontend, testenv]
---

# Provider Channel Participation Settings Implementation Plan

## Feature Summary

This plan delivers the approved `conversation-260801` provider channel
participation snapshot as a reviewable stacked PR series. It adds an explicit
first-mention choice between parent-channel and thread conversations, preserves one
selected Agent per provider parent channel, and exposes provider-native settings for
Slack and Discord.

An unconfigured top-level mention may create only route-neutral setup state, including
the source Resource required for provider-history and security scope. It must not
resolve or create the selected location's target conversation Resource, connected
Binding, AgentSession, canonical mailbox input, wake, Channel Work, or AgentRun before
an authorized human selects a conversation location. Once a selection commits, the
latest eligible mention frozen by the setup claim continues exactly once through the
existing conversation-position and canonical-mailbox authorities.

Provider-visible setup, confirmation, and settings delivery remain independent
projections. Their delivered, failed, unknown, or ambiguous outcomes never gate or
roll back canonical mailbox admission, Session wake, or AgentRun creation.

## Authoritative Inputs

- Requirements:
  `docs/azents/requirements/conversation-260801-provider-channel-participation.md`
  (`conversation-260801/REQ`)
- ADR:
  `docs/azents/adr/conversation-260801-provider-channel-participation.md`
  (`conversation-260801/ADR`)
- Design:
  `docs/azents/design/conversation-260801-provider-channel-participation.md`
  (`conversation-260801/DESIGN`)
- Current behavior:
  - `docs/azents/spec/domain/external-channel.md`
  - `docs/azents/spec/domain/agent.md`
  - `docs/azents/spec/domain/conversation.md`
  - `docs/azents/spec/flow/external-channel-provider-ingress.md`
  - `docs/azents/spec/flow/external-channel-authorization.md`
  - `docs/azents/spec/flow/external-channel-delivery.md`
  - `docs/azents/spec/flow/external-channel-lifecycle.md`
  - applicable External Channel management specs

ADR D5 supersedes D3 and D4 only for first-source ownership: the latest eligible
mention replaces the pending continuation source until selection freezes one
revision. ADR D10 supersedes D1 only for active parent-setting identity and
cardinality: one selected route and one active participation setting exist per
connection and provider parent channel, and parent traffic never fans out.

## Delivery Shape

The feature spans PostgreSQL schema, synchronous ingestion, authorization replay,
provider controls, provider delivery, lifecycle, public management APIs, generated
clients, Web projections, deterministic provider fakes, E2E, rollout, and Living
Specs. These have sequential interfaces and independent review boundaries, so the
feature uses stacked PRs.

Stack prefix: `Provider channel participation`

| Order | PR | Deliverable | Base dependency |
| --- | --- | --- | --- |
| 1 | Design baseline | Approved Requirements, ADR, Design, and docs index | `main` |
| 2 | Implementation plan | Phase boundaries, ownership, validation matrix, fixtures, rollout, and removal mapping | PR 1 |
| 3 | Phase 1 — Schema and domain foundation | Additive enums, tables, provenance, parent Resource contracts, repositories, migration, and disabled rollout gate | PR 2 |
| 4 | Phase 2 — Setup, ingress, and parent Session | Setup state machine, latest-source replay, authorization branches, location-aware routing, Channel/Threads behavior, and concurrency | PR 3 |
| 5 | Phase 3 — Slack controls | Slash, shortcuts, settings controls, manifest contract, parent delivery, and Slack fake coverage | PR 4 |
| 6 | Phase 4 — Discord controls | Command-set reconciliation, settings interactions, direct parent delivery, and Discord fake coverage | PR 5 |
| 7 | Phase 5 — Lifecycle, management, Web, and rollout | Invalidation, route-default replacement/clear, APIs, generated clients, Web projections, presence reconciliation, rollout gate, and observability | PR 6 |
| 8 | Integrated validation | Complete deterministic E2E, prerequisite checks, strict implementation/spec comparison, removal absence audit, and fixes | PR 7 |
| 9 | Spec promotion | Spec review, Living Spec updates, and matching `implemented` date on Requirements and Design | PR 8 |
| 10 | Cleanup | Remove this plan and every feature phase execution plan | PR 9 |

Create each PR before starting the next phase. Create the complete stack before
monitoring stack-wide CI. Merge only from front to back and only after explicit
requester approval for each merge.

## Implementation Ownership and Review

| Role | Assigned owner | Responsibilities |
| --- | --- | --- |
| Primary orchestrator and implementation owner | `/root` | Phase plans, implementation, shared interfaces, integration, validation, branches, commits, PRs, checkpoints, and scope control |
| Independent reviewer | `/root/conversation-260801-independent-reviewer` | Read-only contract review for every implementation, validation, and spec phase |

The reviewer remains separate from implementation and receives each phase execution
plan, authoritative inputs, owned diff, validation evidence, removal obligations, and
scope-drift checkpoint. Required corrections are limited to Requirements/Design,
security or data-loss, and material convention/interface defects. The same reviewer
performs targeted re-review only when those criteria apply.

## Stable Cross-Phase Contracts

- PostgreSQL conversation position is the sole durable provider ordering and duplicate
  authority.
- Canonical mailbox identity is the sole accepted-input and pending wake-recovery
  authority.
- Provider callbacks, setup claims, interactions, controls, and delivery attempts are
  never execution queues.
- External Channel principals are provider provenance and invocation authority, never
  Azents Users or execution Users.
- One connection and provider parent channel have at most one selected Multi route,
  one active participation setting, and one connected parent Binding.
- An exact existing connected thread Binding wins without requiring or backfilling a
  participation setting.
- Every Binding stores a concrete `mention_only` or `all_messages` mode. The setting
  supplies only the default for future Bindings, except that a Channel-mode mutation
  atomically updates the connected parent Binding.
- A terminally disconnected Binding, invalidated setting, or expired setup claim is
  never reactivated.
- Locks are acquired as conversation lock, participation lock, then database
  transaction. Database row order is connection, channel default and route,
  participation setting, setup claim, conversation position, Resource, Binding, then
  Session/mailbox/work rows.
- Provider I/O is never performed while conversation, participation, or database
  locks are held.
- Logs, metrics, provider-fake evidence, and exceptions exposed to operators are
  English and content-free. They exclude credentials, tokens, signatures, raw
  payloads, message text, provider URLs, provider identifiers, Azents identifiers,
  and sensitive exception text.
- Public API source changes are followed by OpenAPI dump and generated Python and
  TypeScript client regeneration. Generated clients are never edited manually.
- E2E creates state only through signed provider callbacks, public APIs, generated
  clients, or rendered UI. Direct product database writes are forbidden; bounded
  `SELECT` evidence is allowed.

## Phase 1 — Schema and Domain Foundation

### Outcomes

- Add conversation-location, participation-setting status, setup-claim status,
  parent Resource type, interaction linkage, versioned presence origin or marker, and
  exactly-one actor provenance contracts.
- Add participation setting and setup claim records with restrictive foreign keys,
  generation/source-revision fencing, partial active uniqueness, and required indexes.
- Change Multi channel-default provenance to exactly one Azents User or provider
  principal without mapping the provider principal to a User.
- Add repository and domain operations for locked reads, creation, replacement,
  source revision, selection freeze, invalidation, and parent Resource identity.
- Preserve existing thread Resources, Bindings, Sessions, modes, positions, and
  history without backfill.
- Add an expand-then-enable feature gate. New setting, claim, and parent Resource
  writes remain disabled in this phase.

### Data and Migration Boundary

Generate linear Alembic revisions from the current single head. PostgreSQL enum models
use `create_type=False`; migration code owns enum creation, expansion, and downgrade
handling. Update `python/apps/azents/db-schemas/rdb/revision`. Add no setting, claim,
Resource, Binding, Session, conversation position, or provider-control backfill.
Migration tests must cover upgrade, downgrade where supported, restrictive foreign
keys, active uniqueness, exactly-one actor checks, and preservation of legacy rows.

### Interfaces Fixed for Phase 2

- Typed participation setting and setup claim DTOs and statuses.
- Participation lock key `(connection_id, provider_parent_channel_id)`.
- Repository operations that accept explicit expected generation/source revision.
- Parent Resource provider-key representation distinct from thread Resources.
- Read-compatible rollout gate that prevents new writes until all runtime processes
  can deserialize every new enum and table.

### Primary Validation

- Migration graph and schema revision tests.
- Model, enum, constraint, and repository tests.
- Focused Ruff and Pyright.
- Full feasible backend Pytest for touched domains.
- Repository search and exhaustive enum handling audit.

## Phase 2 — Setup, Ingress, and Parent Session

### Outcomes

- Intercept an eligible unconfigured top-level invocation after resolving or creating
  only its route-neutral source Resource, but before resolving or creating the target
  parent/thread conversation Resource, Binding, Session, mailbox, wake, Work, or
  AgentRun. The source Resource remains the provider-history, selector, access, and
  security-scope authority until location selection.
- Create or replace one channel-scoped setup claim whose latest eligible mention owns
  the continuation source until selection freezes one revision.
- Support the Multi selector transition from no selected Agent to one authorized
  channel default, then resume location setup without creating a Binding.
- Support restricted Allow by committing authorization and resuming setup without
  entering the legacy immediate-Binding replay branch.
- Complete location selection idempotently and replay the selected trigger exactly
  once through provider-history, conversation position, canonical mailbox, and wake.
- Add a bounded recovery path that prioritizes selected setup replay before newer
  configured top-level ingestion.
- Resolve `parent_channel` Resources explicitly for Channel mode and preserve exact
  thread Resource precedence.
- For initial Channel setup, recover the frozen selected claim source before admitting
  newer configured ingress, and create one parent Binding and root Session from that
  selected source exactly once. A newer message cannot substitute for or overtake a
  selected-but-not-yet-accepted continuation.
- For a later `Threads` to `Channel` transition, or a valid Channel setting whose
  previous parent Binding was terminally disconnected, create no empty Session. The
  next eligible top-level mention creates a new parent Binding and root Session.
  Every new Binding copies the setting's required concrete response mode.
- Reuse the parent Session for later eligible top-level traffic. Keep provider thread
  traffic isolated.
- Implement parent and thread response predicates, settings transitions, source and
  generation revalidation, and the canonical lock order.

### Integration Boundary

The provider-neutral service owns setup authorization and mutation. Slack and Discord
phases only authenticate and lower provider-native controls into this service. Phase 2
may use provider-neutral control intents and test adapters, but it does not add final
provider command registrations, manifest changes, or provider-specific UI copy.

### Primary Validation

- Setup side-effect absence before selection.
- Latest mention replacement and selection-before/after replacement races.
- Duplicate selection, replay, position advancement, crash-boundary recovery, and one
  mailbox/one logical wake convergence.
- Selected-claim priority proving newer top-level ingress cannot overtake or replace a
  selected-but-not-yet-accepted continuation.
- Restricted Allow and Multi selector paths create no Binding or Session before
  location selection.
- Existing thread Binding precedence with no setting.
- Parent Resource and Binding uniqueness; no thread fallback or route fan-out.
- Channel/Threads mode copy and transition behavior.
- Lock-order and stale-history generation fencing tests.
- Focused and applicable full backend Ruff, Pyright, and Pytest.

## Phase 3 — Slack Provider-Native Controls

### Outcomes

- Extend signed HTTP and Socket Mode admission with explicit Slash Command,
  invocation shortcut, settings shortcut, component, and modal discriminators.
- Add `/azents` parent settings and trustworthy thread settings behavior.
- Add message-context setup/settings resolution and binding-scoped Conversation
  settings beside View session.
- Render setup, Agent selection, current state, mutation confirmation, stale,
  unsupported, and `all_messages` guidance without retaining trigger IDs or response
  URLs.
- Update the copy-ready Slack manifest contract with `commands` scope, `/azents`, both
  message shortcuts, interactivity, transport-correct URLs, and existing-installation
  readiness guidance.
- Deliver parent-channel replies without `thread_ts`; preserve root `thread_ts` for
  thread Resources.
- Ensure provider delivery outcomes remain independent from committed settings,
  mailbox, wake, and AgentRun state.

### Primary Validation

- Signed JSON/form parsing, HTTP/Socket parity, explicit discriminator, stale scope,
  duplicate callback, modal, and component tests.
- Manifest structure and transport-specific URL tests.
- Parent delivery fake assertion for absent `thread_ts`; thread assertion for present
  root `thread_ts`.
- Unsupported thread scope never mutates parent settings.
- Setup and settings delivery failure/ambiguity leaves canonical state committed and
  re-surfaceable.
- Focused Slack fake and provider service tests plus applicable backend quality checks.

## Phase 4 — Discord Provider-Native Controls

### Outcomes

- Reconcile a required Azents-owned command role set through list/create/update/delete
  while preserving unrelated customer commands.
- Persist a role-to-command-ID map and current capability proof instead of one singular
  Message Command ID.
- Add parent settings, trustworthy thread settings, message context, components,
  autocomplete, and modal behavior through signed interaction scope.
- Render setup, Agent selection, current state, mutation confirmation, stale,
  unsupported, and `all_messages` guidance without retaining interaction tokens or
  callback URLs.
- Deliver parent Resource replies directly to the parent channel without provisioning
  a Discord thread. Preserve deterministic thread provisioning for thread Resources.
- Ensure provider delivery outcomes remain independent from committed settings,
  mailbox, wake, and AgentRun state.

### Primary Validation

- Command-set reconciliation tests covering distinct required role IDs, recognized
  obsolete Azents command removal, and unrelated command preservation.
- Signed interaction, scope, stale generation, duplicate callback, component,
  autocomplete, and modal tests.
- Parent delivery fake assertion proving no ensure-thread call; thread assertion
  preserving existing provisioning.
- Unsupported thread scope never mutates parent settings.
- Delivery failure/ambiguity and safe re-surface behavior.
- Focused Discord fake and provider service tests plus applicable backend quality
  checks.

## Phase 5 — Lifecycle, Management, Web, and Rollout

### Outcomes

- Extend selected-Agent replacement and clear into one locked mutation that
  invalidates the old setting and setup claim, expires linked interactions,
  terminally disconnects only the old parent Binding, and preserves its Session,
  history, and every thread Binding.
- Extend route removal, Agent decommission/deletion, terminal connection disconnect,
  Session archive, and cleanup/finalization paths with the designed participation
  lifecycle. Transient degraded or reconnect-required health preserves valid settings.
- Preserve a valid setting when an independently disconnected or archived parent
  Binding ends; later eligible Channel traffic creates a new Binding and Session.
- Add shared provider-principal and Web AgentAdmin mutation units without synthetic
  User or administrator bypass.
- Extend channel-default impact previews and mutation results with setting, claim, and
  parent-Binding counts.
- Extend `ManagedBinding` and related projections to distinguish parent and thread
  location, concrete response mode, connectedness, Session navigation, Work, and
  delivery evidence.
- Dump OpenAPI and regenerate Python and TypeScript public clients. Update tRPC,
  relevant query invalidation, Workspace integration summaries, Agent Settings
  context, Session Channels rendering, localized copy, stories, and responsive states.
- Add version-2 joined-presence settings controls for new Bindings and a bounded
  existing-Binding reconciler with distinct `binding_settings_available` origin.
  Exclude disconnected Bindings and never rewrite provider history or blindly retry
  failed, unknown, or ambiguous provider creates.
- Add sanitized structured evidence and implement the read-compatible rollout gate
  and deployment-controlled enablement mechanism. Retain the compatibility safeguard
  through this implementation stack. Repository tests cannot prove that every
  production process runs the compatible binary, so gate removal is a separately
  authorized post-deployment action or follow-up PR backed by actual rollout evidence.

### Primary Validation

- Route A-to-B and clear lifecycle tests preserving thread Bindings and history.
- Route removal, Agent lifecycle, connection disconnect, Session archive, restore,
  purge/finalizer, and no-revival tests.
- Provider-principal and User actor provenance tests for every mutation.
- Management route/service/repository/OpenAPI tests and generated-client drift checks.
- Existing and new Binding presence-control reconciliation tests for delivered,
  failed, unknown, missing, and disconnected states.
- TypeScript format, lint, typecheck, build, stories, and focused browser-facing tests.
- Rollout gate tests across server, worker, gateway, migration, and feature-enable
  boundaries.
- Sanitized logging and evidence tests.

## Integrated Validation

PR 8 runs the stable integrated diff through all required lanes, records commands,
environment, sanitized results, and fixes discovered defects without changing product
intent.

Validation evidence may be reused only while the diff is unchanged, prerequisite
snapshots remain fresh, and the execution environment is equivalent. A discovered fix
invalidates and reruns every affected matrix entry. A fix that crosses a shared
interface, persistence authority, authorization boundary, provider-neutral ingestion
path, generated contract, or lifecycle boundary reruns the complete matrix.

### E2E Primary Matrix

| Scenario | Entry surface | Required evidence |
| --- | --- | --- |
| First unconfigured Slack mention | Signed callback and Slack fake | Setup control exists; no Binding, Session, mailbox, wake, Work, or AgentRun |
| First unconfigured Discord mention | Gateway callback and Discord fake | Same setup gate and sanitized evidence |
| Latest mention replacement | Two explicit mentions and stale/current controls | One claim; latest frozen source executes once; earlier source does not execute independently |
| Selected replay priority | Selection commit, delayed replay barrier, then newer top-level ingress | Frozen selected source reaches canonical mailbox first and executes once; newer ingress cannot overtake it |
| Multi Agent selection | Provider selector with no channel default | Only currently invokable routes; one selected default; setup continues without Session |
| Setup concurrency | Concurrent authorized selections | First valid mutation wins; loser shows current setting; at most one Session |
| Restricted Allow | Approval API and provider setup control | Grant commits without Binding/Session; setup resumes; later selection releases one mailbox input |
| Channel behavior | Slack and Discord parent channels | One reused Session; parent replies; provider thread messages excluded |
| Threads behavior | Multiple root invocations | Independent thread Bindings and Sessions |
| Channel modes | Provider settings and Session evidence | `mention_only` ignores ordinary traffic; `all_messages` admits eligible top-level humans |
| Threads modes | Parent setting and old/new thread Bindings | New Binding copies default; existing Binding keeps mode |
| Provider entry points | Slash/command, presence, and context actions | Safe scopes converge on canonical setting; unproven thread scope is unsupported |
| Slack installation contract | Manifest and validation surfaces | Commands scope, Slash, shortcuts, interactivity, URLs, and readiness guidance |
| Discord command contract | Activation and Discord fake | Required roles and IDs retained; obsolete owned command removed; unrelated command preserved |
| Channel to Threads | Provider settings | Parent Binding terminal; history and thread Bindings retained |
| Threads to Channel | Provider settings then mention | No empty Session; mention creates new parent Binding/Session |
| Selected Agent A to B | Channel-default replacement | A setting invalid and parent Binding terminal; threads/history retained; B unconfigured |
| Clear selected Agent | Channel-default clear | No selected Agent, active setting, pending claim, or parent Binding; history/threads retained |
| Duplicate and stale controls | Replayed callbacks and old generations | Current state returned; no duplicate mutation or execution |
| Delivery failure and ambiguity | Fake provider barriers | Canonical setting/mailbox/wake/Run unaffected; safe re-surface remains |
| Existing Binding controls | Reconciler plus both provider fakes | One versioned control with View session and Conversation settings; no history rewrite |
| Lifecycle invalidation | Route, Agent, connection, Session lifecycle | Correct invalidation/disconnect; no revival; history retained |
| Management and Web | Public generated client and rendered UI | Parent/thread distinction, impact counts, settings summaries, responsive copy |
| Redaction | Fake evidence and captured logs | No secrets, identifiers, text, raw payload, private URL, or sensitive exception data |

### Fixture and Prerequisite Requirements

The deterministic Slack fake must support signed Events API and interaction forms,
Socket envelopes, Slash Commands, message shortcuts, modal/component callbacks,
parent-versus-thread delivery targets, manifest validation, one-attempt failure and
ambiguous outcomes, and sanitized control evidence.

The deterministic Discord fake must support typed Gateway messages, signed command and
component interactions, command list/create/update/delete reconciliation, role-to-ID
state, parent direct delivery, thread provisioning, one-attempt failure and ambiguous
outcomes, and sanitized control evidence.

Public API and browser tests require generated clients and the real application
surface. Required prerequisites fail with an actionable error; they never silently
skip. Live provider credentials are optional and cannot be required for the mandatory
matrix. Any optional live test reports a skip reason without substituting for fake
coverage.

### Validation Commands

Run the exact applicable repository commands from each project root and record their
versions and results:

- docs index generation and snapshot validation;
- backend Ruff format/check, Pyright, focused Pytest, full feasible Pytest, and
  migration tests;
- public OpenAPI dump and Python/TypeScript generated-client drift checks;
- TypeScript format, lint, typecheck, build, stories, and applicable browser tests;
- deterministic Slack and Discord provider E2E;
- repository searches and exhaustive matching for every removal obligation;
- `git diff --check` and scope comparison against every phase plan.

No E2E may write product database state directly. Bounded database reads may be used
only for absence, count, lifecycle, and redaction evidence not exposed by a public
surface.

## Design Removal Obligations

| Obsolete unit or assumption | Owning PR | Prerequisite | Replacement | Required absence evidence |
| --- | --- | --- | --- | --- |
| Eager top-level target thread Resource, Binding, Session, and mailbox creation | PR 4 | Setup-claim persistence, route-neutral source Resource, and rollout gate from PR 3 | Setup claim gate and selected replay | No-side-effect tests and search showing no eager unconfigured target path |
| `_resolve_resource` defaulting every new target Resource to thread | PR 4 | Parent Resource enum, provider-key contract, and repositories from PR 3 | Exhaustive location-aware resolver | Parent/thread tests and exhaustive Resource matching |
| Slack parent replies always carrying root `thread_ts` | PR 5 | Parent Resource and Binding behavior from PR 4 | Resource-aware target lowering | Fake payload absence/presence assertions |
| Discord root Resources always provisioning a delivery thread | PR 6 | Parent Resource and Binding behavior from PR 4 | Direct parent delivery | No ensure-thread evidence for parent Resources |
| Multi channel default requiring an Azents User actor | PR 3 | Exactly-one actor schema and principal FK design | Exactly-one User-or-principal provenance | Constraint, migration, and provider selection tests |
| Participation setting supporting only provider-principal provenance | PR 3 and PR 7 | Exactly-one actor schema in PR 3 before Web mutations in PR 7 | Exactly-one User-or-principal provenance used by provider and Web mutations | Constraint and mutation provenance tests |
| Access Allow always creating a Binding | PR 4 | Setup claim linkage and route-neutral source authority from PR 3 | Setup-linked authorization branch | No Binding/Session and no `replay_access_allow` path for setup-linked requests |
| Resource-bound selector always replaying toward a Binding | PR 4 | Setup claim linkage, source revision, and channel-default provenance from PR 3 | Setup-linked Agent selection and `pending_location` transition | Selector tests with no Binding and current claim revision |
| Slack manifest without commands, shortcuts, or interactivity | PR 5 | Typed provider-neutral setup/settings operations from PR 4 | Complete installation contract | Manifest tests for HTTP and Socket Apps |
| Selector-only Slack interaction dispatch | PR 5 | Explicit setup/settings interaction kinds and scope contracts from PR 4 | Explicit typed dispatch | Parser tests and repository search for no settings fallthrough |
| Discord activation storing one Message Command ID | PR 6 | Role-based command capability schema from PR 3 and provider-neutral settings operations from PR 4 | Required role-to-ID command map | Reconciliation and persisted-capability tests |
| Session presence exposing only View session | PR 5, PR 6, and PR 7 | Versioned control origin from PR 3, provider renderers in PRs 5/6, reconciler in PR 7 | Versioned settings action and bounded legacy reconciliation | New/existing Binding control tests without history rewrite |
| Provider participants routed through AgentAdmin-only mutation | PR 7 | Shared setting repository and provider authorization established by PRs 3–6 | Shared mutation unit with separate provider and Web authorization | No synthetic User/admin bypass tests |
| Route/default replacement ignoring participation state | PR 7 | Setting/claim invalidation and parent Binding lifecycle contracts from PRs 3–4 | Atomic invalidation and parent-Binding terminalization | A-to-B E2E and active-row absence queries |
| Channel-default clear invalidating only route default | PR 7 | Shared old-route terminalization implemented for replacement | Shared old-route terminalization | Clear E2E and active-row absence queries |
| Multiple independently effective parent Agent settings or fan-out | PR 3 and PR 4 | Active uniqueness in PR 3 before configured ingress in PR 4 | One selected route, setting, and parent Binding | Unique constraints, ingress tests, and no route enumeration |
| Legacy presence idempotency reusing old payload | PR 7 | Distinct versioned delivery origin from PR 3 and final provider control payloads from PRs 5–6 | Distinct versioned reconciliation origin | Delivered/failed/unknown/missing/disconnected tests |

A phase cannot close while its owned obsolete behavior remains authoritative. Search
results alone are not sufficient where behavior requires an executable absence test.

## Spec Impact and Promotion

Current specs are not rewritten in intermediate phases unless a phase cannot remain
accurate without a narrowly scoped correction. PR 9 runs `spec-review`, compares the
integrated implementation and E2E evidence against every relevant current spec, and
updates:

- `docs/azents/spec/domain/external-channel.md`;
- `docs/azents/spec/domain/agent.md` when Agent defaults or management authority need
  clarification;
- `docs/azents/spec/domain/conversation.md`;
- `docs/azents/spec/flow/external-channel-provider-ingress.md`;
- `docs/azents/spec/flow/external-channel-authorization.md`;
- `docs/azents/spec/flow/external-channel-delivery.md`;
- `docs/azents/spec/flow/external-channel-lifecycle.md`; and
- applicable External Channel management and E2E strategy specs.

Only after implementation and mandatory validation are complete, add the same actual
KST completion date as `implemented` in the Requirements and Design. Do not predeclare
the date; if completion occurs on August 1, 2026, use `2026-08-01` at that time. Do
not edit the accepted ADR. Any newly discovered hard-to-reverse product decision
requires a new feature-design snapshot rather than changing this accepted snapshot.

## Rollout and Rollback

1. Apply additive schema and enum expansion.
2. Deploy code that reads all new rows and enum values while participation writes are
   disabled.
3. Reconcile provider command registrations, refresh Slack installation guidance, and
   deploy regenerated Web clients.
4. Verify every server, worker, and gateway process runs the compatible binary.
5. Enable setup, setting, and parent Resource writes.
6. Run the bounded existing-Binding settings-control reconciler.
7. After actual compatible rollout evidence exists and explicit production-change
   approval is granted, remove the temporary gate through a separately authorized
   deployment action or follow-up PR. The 10-PR implementation stack retains the
   safeguard and does not infer production compatibility from CI.

Before enablement, additive schema and compatible code may roll back independently.
After any setting, claim, or parent Resource is written, disable new setup and prefer a
forward fix. Do not roll back to a binary that cannot deserialize the new enum values.
Database downgrade is not the operational rollback path after writes.

Existing Slack installations require a refreshed manifest or equivalent manual
configuration before Slash and context controls are available. Backend readiness and
customer App-configuration readiness are reported separately.

## Mandatory Phase Execution Plan and Checkpoints

Before any implementation edit or delegation begins for PRs 3 through 7, create,
store, and report a separate tracked phase execution plan under `docs/azents/plans/`.
A phase summary in this plan, chat, or PR body is not a substitute. Every phase plan
must use the required `## Phase Execution Plan` structure and include:

- phase number and name;
- branch and stacked base;
- PR boundary;
- completed inputs;
- observable deliverables;
- explicit non-goals;
- fixed interfaces;
- owned Design removal obligations;
- absence-verification method;
- a workstream table containing owner, owned paths, dependencies, output, and
  validation;
- integration order;
- exact independent review scope, criteria, inputs, and output;
- final validation commands;
- scope-drift comparison; and
- context checkpoint covering completed behavior, changed interfaces, evidence,
  remaining scope, relevant paths, risks, and blockers.

Implementation starts immediately after that gate unless the plan exposes a new
product decision. Before each implementation PR opens, update its phase checkpoint
with completed behavior, changed interfaces, validation evidence, owned removals and
absence proof, remaining stack scope, relevant paths, risks, blockers, reviewer
result, and scope-drift verdict. The next phase starts only after the current PR
exists.

If a phase changes an interface required by a later phase, update this plan and the
current phase plan in the same PR before implementation continues. Routine engineering
choices follow the approved Design. A newly exposed product decision returns to
feature design instead of being decided in code.

## Known Blockers and External Actions

There are no implementation blockers in the approved snapshot.

External actions are intentionally separated from implementation:

- GitHub merge requires explicit requester approval for each PR.
- Production deployment and provider App reconfiguration require explicit approval.
- Rollout-gate removal requires actual compatible production rollout evidence and a
  separately authorized deployment action or follow-up PR.
- Existing Slack customer Apps require user-applied manifest or manual configuration
  updates for the new provider-native entry points.
- Live-provider verification is optional supporting evidence and never replaces the
  deterministic provider-fake matrix.

## Completion and Cleanup Gate

The feature is complete only when:

- all implementation phases have independent review with required corrections closed;
- the deterministic provider, public API, and applicable UI E2E matrix passes;
- every Design removal obligation has executable and search-based absence evidence;
- generated clients match the dumped public OpenAPI source;
- Living Specs match the implemented behavior;
- Requirements and Design share the verified implementation date; and
- all stacked PRs have completed required CI.

PR 10 then removes this implementation plan and every
`conversation-260801-provider-channel-participation-phase-*` execution plan. Current
Living Specs, immutable implemented Requirements, accepted ADR, implemented Design,
and code become the source of truth.
