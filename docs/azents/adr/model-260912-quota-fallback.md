---
title: "Model Quota Fallback Decisions"
created: 2026-09-12
tags: [models, architecture, reliability, engine]
document_role: primary
document_type: adr
snapshot_id: model-260912
---

# Model Quota Fallback Decisions

- Snapshot: `model-260912`
- Document reference: `model-260912/ADR`
- Requirements: [Model Quota Fallback Requirements](../requirements/model-260912-quota-fallback.md) (`model-260912/REQ`)
- Mode: Autonomous after explicit requester delegation. The requester directly accepted `ADR-D4`;
  the delegated autonomous technical decision owner accepted the remaining decisions and reviews the
  complete Design.

## Context

The confirmed `model-260912/REQ` requires one Agent-owned semantic label to contain one to five ordered physical model candidates. A classified quota or billing failure advances immediately to the next compatible candidate, marks the Workspace-scoped integration/model identity unavailable for five minutes, and never repeats that quota candidate in the same logical operation. Main sampling uses the Default label; compaction and title generation use the Lightweight label. Recovery preserves frozen in-flight routing, while normal responses remain free of fallback markers and the Composer/model picker owns user-facing availability and one-shot Primary recovery.

Current Agents and Workspace defaults store each selectable label as one model-selection snapshot plus settings in ordered JSONB arrays. The Session inference snapshot and `RunRequest` freeze one physical model. `agent_runs.retry_state` durably preserves one model turn's failed-attempt budget and handover, but it has no candidate chain, cursor, or cross-Session breaker state. All classified provider failures currently consume the same retry budget. The provider taxonomy already distinguishes `quota_or_billing` from `rate_limit`, canonical transcript reconstruction supports cross-provider lowering before output admission, and successful output plus retry-state clear commit atomically.

Redis is optional volatile coordination and cannot own cooldown or probe correctness. Automatic title generation is independent best-effort work without an AgentRun, while compaction shares the foreground Run's failure controller. The public Agent and Workspace v1 contracts expose the singular label/model shape and are consumed by generated clients and the Web application.

## Material Decision Map

### Fixed or derived outcomes

- Semantic model labels remain the only Session, mailbox, Scheduled Task, External Channel, command, continuation, and subagent routing intent.
- Candidate chains contain one to five candidates and preserve candidate-owned settings.
- Explicit reasoning effort and execution options are retained; incompatible candidates are skipped.
- Only classified `quota_or_billing` advances the candidate chain; ordinary `rate_limit` keeps existing behavior.
- Workspace cooldown identity is `(workspace, integration, model)`, lasts five minutes, and outlives removal from an Agent chain until expiry.
- Half-open recovery is single-flight and uses a real request. Redis loss cannot break correctness.
- Agent settings changes affect fresh operations; in-flight operations use a frozen chain.
- Main sampling uses Default; compaction and automatic title use Lightweight.
- Assistant response content has no fallback marker. Composer status and model-picker recovery remain user-facing.
- Database transactions contain no provider, Redis, broker, filesystem, or other external I/O.

### Material decisions

- [x] `model-260912/ADR-D1` — Agent/Workspace persisted chain shape and existing-row migration.
- [x] `model-260912/ADR-D2` — Frozen active model-operation state and candidate progression across retry/handover.
- [x] `model-260912/ADR-D3` — Workspace cooldown and half-open probe durable authority.
- [x] `model-260912/ADR-D4` — Public v1 model-option contract transition.
- [x] `model-260912/ADR-D5` — Session one-shot Primary reservation and live availability contract.
- [x] `model-260912/ADR-D6` — Main, compaction, and title execution integration with existing retry boundaries.
- [x] `model-260912/ADR-D7` — Provenance, diagnostics, metrics, and deterministic verification authority.

### Agent-owned implementation details

Exact class, table, column, endpoint, event, helper, hook, metric, log, fixture, story, and file names remain implementation-owned when they preserve the accepted ownership and lifecycle decisions. Equivalent local decomposition, typed helper boundaries, bounded internal constants other than the approved five-minute TTL and one-to-five candidate limit, and test organization are also implementation-owned.

## Decisions

### model-260912/ADR-D1: Store a uniform candidate list inside each selectable label

**Affected requirements:** `model-260912/REQ-1`, `REQ-2`, `REQ-5`, `REQ-7`

**Accepted on:** 2026-09-12 under the requester's delegated technical authority.

Each stored Agent and Workspace selectable model option owns `label`, `subagent_enabled`,
`subagent_guidance`, and one ordered `candidates` list. Every candidate stores one complete
`AgentModelSelection` snapshot plus candidate-local context-window, output-token, and built-in-tool
settings. The label list remains ordered and bounded by its existing label-count policy; each nested
candidate list is independently bounded to one through five items. The first candidate is the
Primary source for label-level selectable capabilities and the denormalized main/lightweight
selection mirrors.

The Agent and Workspace JSONB values remain the configuration source of truth. The existing
denormalized `model_selection` and `lightweight_model_selection` columns remain derived mirrors of
the selected labels' Primary candidates and are updated in the same repository transaction as the
chain. Runtime routing never reconstructs candidates from current catalog data.

One generated migration lifts existing `settings.subagent_enabled` and
`settings.subagent_guidance` to the label, moves the remaining model-scoped settings beside the
existing model selection in the first candidate, and writes the canonical nested shape for Agents
and Workspace defaults. It replaces outer-only database checks with checks that also require
one-to-five candidates per option. Application validation owns trimmed unique labels, duplicate
`(integration, model)` rejection within a label, candidate snapshot resolution, label-policy
validation, and candidate-local settings validation. The final code has one canonical nested shape
and no legacy row decoder.

**Rejected alternatives:**

- A normalized candidate table was rejected because the complete ordered option list is replaced as
  one settings form, each model selection is already an immutable JSON snapshot, and a separate
  relation would add row lifecycle, ordering, and join authority without an independently managed
  candidate identity.
- Keeping an asymmetric internal Primary plus `fallback_candidates` shape was rejected because it
  would give the first candidate different storage and editing semantics from reorderable later
  candidates.
- Resolving fallback models from the live catalog at execution time was rejected because it would
  violate Agent snapshot ownership and make retries depend on mutable provider listings.

**Risks:**

- Every Agent/Workspace serializer, fixture, and validation path must migrate together; partial
  rollout would make strict typed decoding fail.
- The retained denormalized Primary mirrors must remain derived-only and atomically consistent so
  they do not become a second chain authority.

### model-260912/ADR-D2: Add durable bounded model-operation slots beside retry state

**Affected requirements:** `model-260912/REQ-2`, `REQ-3`, `REQ-5`, `REQ-8`

**Accepted on:** 2026-09-12 under the requester's delegated technical authority.

Each `AgentRun` stores a bounded typed operation container with at most one foreground-sampling slot
and at most one compaction slot. Each slot owns a stable operation identity and kind, the requested
semantic label and explicit request options, the complete ordered candidate snapshots, the current
candidate cursor, one current/final outcome record per candidate, and any half-open probe claim
attached to that operation. The slots are separate from `retry_state`: model-operation state owns
candidate routing, while retry state continues to own retry count, history, and backoff for the
currently selected candidate's non-quota failure. Compaction cannot replace or clear a prepared
foreground chain.

Fresh preparation resolves and persists the complete chain before the first provider call. Each
candidate dispatch derives the single physical `SessionInferenceState` and `RunRequest` from that
frozen operation state. The Session snapshot continues to describe the exact candidate currently
being lowered and its effective limits; it no longer has to represent the whole chain. Follow-up
model steps for the same promoted input retain the active chain and cursor. A later input or explicit
profile transition creates a new operation snapshot from current Agent settings.

When a normalized quota failure reaches the Run controller, one database-only transaction records
the candidate outcome, advances the cursor, updates Workspace cooldown authority, and clears any
ordinary retry state that cannot apply to the next candidate. The next provider call begins only
after that transaction commits. Non-quota failures leave the cursor unchanged and continue through
the existing retry controller. Recovery claims the same Run and active operation state, so restart
or handover cannot reset the chain or forget a durably observed quota failure.

Intermediate successful foreground calls may append tool calls, tool results, and turn provenance
while retaining the foreground slot for the same promoted input. The slot clears only at final
end-turn completion after admitted client tools finish, replacement by a newly promoted
input/profile boundary, User Stop, or terminal Run finalization. Compaction success, stale-plan
detection, cancellation, and terminal compaction failure clear only the compaction slot. Run
terminalization clears both slots defensively. A manual failed-run retry creates a new Run and
therefore new operation slots and chain snapshots.

**Rejected alternatives:**

- Extending only `SessionInferenceState` was rejected because Session state represents one currently
  applied physical request and is replaced at turn boundaries; it cannot independently retain a
  candidate cursor and attempt history for Run recovery.
- Embedding candidate routing only inside `retry_state` was rejected because quota progression has
  no retry wait, successful/in-flight candidate calls also need a frozen chain, and retry state is
  cleared on successful output.
- Re-resolving Agent options after every failed attempt was rejected because settings changes during
  backoff or handover would mutate the active operation and could reintroduce already attempted
  candidates.

**Risks:**

- The quota transition must be serialized with the current Session owner generation and Run identity
  so a stale worker cannot advance or regress a newer operation.
- A process can disappear before a provider outcome reaches durable transition. That remains an
  unknown in-flight attempt under the existing recovery contract; only durably observed quota
  outcomes authorize candidate advancement.
- Effective context limits, built-in tools, credentials, and provenance must all be rebuilt from the
  same current candidate snapshot before dispatch.

### model-260912/ADR-D3: Use PostgreSQL cooldown rows with fenced foreground probe claims

**Affected requirements:** `model-260912/REQ-3`, `REQ-4`, `REQ-5`, `REQ-8`

**Accepted on:** 2026-09-12 under the requester's delegated technical authority.

PostgreSQL owns one current cooldown row for each Workspace-scoped
`(llm_provider_integration_id, model_identifier)` identity. The row stores the cooldown deadline, a
monotonic state generation, and an optional bounded half-open probe claim with its owning model
operation and lease deadline. The integration remains the authorization boundary; deleting the
integration removes its irrelevant cooldown rows. Removing a candidate from an Agent or label does
not remove the cooldown row.

Candidate selection reads this durable authority. Before the cooldown deadline, ordinary operations
skip the candidate; only a matching D5 Session reservation transferred into a foreground operation
may perform the approved one-shot bypass. After expiry, one foreground sampling operation
atomically claims the next generation as the half-open probe. Other operations skip that candidate
while the claim remains active. The provider call occurs after the claim transaction commits. Probe
success clears the row only when the operation and generation still match; a normalized quota
failure replaces it with a new five-minute cooldown and higher generation. Every higher-generation
quota transition clears the previous claim owner, immediately revoking any older probe or Session
reservation authority. A crashed probe cannot block permanently because its lease expires, after
which a later foreground operation may claim a higher generation. Stale success or failure
completion cannot clear or renew a newer state.

Automatic compaction and title generation honor active cooldowns and use later candidates, but they
do not acquire half-open probe claims. Background work therefore cannot consume the single recovery
opportunity or write Session-specific reservation/presentation state. A real quota failure observed
by background work still renews the shared physical-candidate cooldown, so every later DB-derived
availability read sees that Workspace-wide fact. Primary recovery is proven by a foreground request,
either the first ordinary request after expiry or the Session one-shot reservation defined by D5.

Redis may cache or publish derived availability hints, but PostgreSQL remains the complete decision
authority. Empty Redis loses only derived notification state; the next read reconstructs current
availability from PostgreSQL. Database time is authoritative for cooldown and probe deadlines.

**Rejected alternatives:**

- Redis locks/TTL keys were rejected because Redis is replaceable volatile coordination and cannot
  provide correctness or recovery after an empty-store replacement.
- Session- or process-local breakers were rejected because concurrent Workers and Sessions could
  issue multiple probes and would forget cooldown on handover.
- A durable cooldown without a fenced probe generation was rejected because late completions from a
  crashed or superseded probe could clear a newer quota failure.
- Allowing title or compaction to claim half-open state was rejected because invisible background
  work could consume user recovery and race a one-shot Primary reservation. Background quota
  failures still update the shared cooldown authority.

**Risks:**

- Cooldown rows remain until a successful foreground probe or integration deletion so expiry cannot
  erase the half-open requirement.
- Database contention concentrates only on a candidate that is leaving cooldown; selection of
  healthy candidates must remain lock-free or use a short non-blocking claim transaction.
- Clock and lease tests must use database time or a deterministic clock boundary rather than sleeps.

### model-260912/ADR-D4: Cleanly replace the public v1 singular option contract

**Affected requirements:** `model-260912/REQ-1`, `REQ-2`, `REQ-6`, `REQ-7`, `REQ-8`

**Accepted on:** 2026-09-12 by the requester.

The public Agent and Workspace model-settings v1 contracts replace each selectable option's singular
`model_selection` and `settings` fields with the canonical label policy plus ordered `candidates`.
Each candidate has one model-selection input or snapshot and candidate-local settings. The option
projects Primary-owned selectable reasoning and execution controls for Composer use without
requiring the browser to intersect or route physical candidates.

The obsolete direct Agent create/update `model_selection` and `lightweight_model_selection` inputs,
the Workspace `default_model_selection` and `default_lightweight_model_selection` compatibility
inputs, and their public response mirrors are removed. `main_model_label` and
`lightweight_model_label` remain the only public default selectors. The internal denormalized
selection columns retained by D1 are not public mutation authority.

This is one coordinated clean cutover of server schemas, OpenAPI, generated Python and TypeScript
clients, Web adapters, fixtures, E2E callers, and Living Specs. Existing persisted Agent and
Workspace values are preserved by the D1 migration, but external callers must update to the new
generated client/schema. The final application has no singular-option compatibility decoder,
deprecated alias, parallel v2 endpoint, or dual mutation path.

**Rejected alternatives:**

- An optional `fallback_candidates` field beside the old Primary fields was rejected because an old
  read-modify-write client could silently erase unknown fallbacks and the public shape would remain
  asymmetric.
- Keeping v1 and adding a separate chain API was rejected because Primary and fallback edits would
  have two mutation authorities, separate authorization/idempotency rules, and an indefinite
  synchronization obligation.
- Returning both old and new shapes was rejected because equivalent fields could disagree and force
  every consumer to choose an authority.

**Risks:**

- External v1 callers must upgrade in the coordinated release; stale callers fail schema validation
  rather than receiving partial behavior.
- Every generated and hand-written adapter must cut over together so a stale Web build cannot submit
  the removed shape.
- Public documentation and release notes must identify the breaking contract explicitly.

### model-260912/ADR-D5: Pair a bounded Session reservation with the Workspace probe lease

**Affected requirements:** `model-260912/REQ-4`, `REQ-5`, `REQ-6`, `REQ-8`

**Accepted on:** 2026-09-12 by the delegated autonomous technical decision owner.

`Primary retry` creates two fenced durable records without issuing a provider call. The concrete root
Session stores the selected label, exact current Primary `(integration, model)` identity, reservation
generation, and creation/expiry timestamps. The D3 Workspace cooldown row stores the matching
exclusive reservation owner. One candidate may have at most one active Session reservation or
active probe claim. The server permits reservation only when that exact Primary has an active
cooldown or an expired cooldown awaiting a half-open probe; a fully healthy Primary returns the
current availability without creating state.

The reservation lease is bounded to five minutes of database time. Explicit cancellation, Session
archive/removal, selected-label or exact-Primary replacement, successful transfer, or lease expiry
releases it. Repeating the same active reservation request from the same Session is idempotent. A
healthy Primary, stale expected label/Primary, or a different active owner returns a bounded conflict
plus the current availability snapshot.

The next compatible foreground request for the same label atomically transfers both reservation
records into its foreground model-operation slot only while the candidate-health generation and
claim still match. Consumption occurs only when that transfer commits; provider dispatch occurs
afterward. An unrelated preparation failure before transfer leaves the reservation intact. A
higher-generation quota transition immediately revokes the Workspace claim. The Session record then
has no routing authority: availability ignores it, transfer/cancel conditionally clears it, and
lease expiry bounds any uncollected row. Success, renewed quota failure, crash recovery, and stale
completion use the fenced D3 operation claim. Draft Sessions cannot reserve because they have no
durable Session owner.

A DB-derived availability projection treats a Session reservation as active only when its exact
candidate identity, health generation, reservation generation, and owner match the current
candidate-health claim. A mismatch projects current cooldown/probe state with no `primary_next` and
triggers best-effort owner invalidation; REST or the next Session mutation performs bounded
conditional cleanup. The projection exposes only Primary public display, state
`available | cooldown | probing | primary_next`, deadline and server time, the first compatible
usable fallback display, and the current Session reservation. It does not expose the complete chain,
another Session owner, or raw provider diagnostics. `/live` and authoritative write snapshots recover
the state; Redis/WebSocket signals are best-effort invalidation rather than authority.

**Rejected alternatives:**

- A Session boolean without a Workspace reservation was rejected because concurrent Sessions could
  both display and issue `Primary next`.
- Issuing a health-check call on click was rejected because the product requires a real-request
  probe.
- Acquiring the claim only when the later message is sent was rejected because another Session could
  consume it after the UI promised `Primary next`.
- An unbounded or Redis-owned reservation was rejected because it could indefinitely block recovery
  or disappear with volatile coordination.

**Risks:**

- A user may hold the unique recovery opportunity without sending work for up to five minutes;
  ordinary fallback remains available during that lease.
- Agent chain edits, Session intent changes, reserve/cancel, and send transfer require exact identity
  and generation fencing.

### model-260912/ADR-D6: Integrate quota progression before each operation's generic retry boundary

**Affected requirements:** `model-260912/REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-7`

**Accepted on:** 2026-09-12 by the delegated autonomous technical decision owner.

Foreground sampling freezes the requested or Default label chain in the foreground AgentRun slot.
Compatibility and cooldown skips are recorded before provider dispatch. A normalized
`quota_or_billing` failure is intercepted before generic failed-run retry persistence: the existing
failed-attempt live projection is discarded, one database-only transition records the candidate
outcome, renews cooldown, advances the cursor, and clears candidate-local retry state, then the next
candidate begins after commit. Each newly selected candidate starts its own existing non-quota retry
budget. Chain exhaustion enters the existing terminal failed-run boundary once and never restarts the
chain. Rate-limit and other failure categories retain current candidate retry/finalizer behavior.

Compaction independently freezes the Lightweight chain in the compaction AgentRun slot. Quota
advances only that slot and does not consume generic compaction retries. The next candidate keeps the
compaction operation identity but rebuilds and revalidates the transcript plan through the existing
stale-plan contract. Non-quota failure uses the current owning Run retry behavior. Success, stale
plan, Stop, cancellation, or terminal failure clears only the compaction slot.

Automatic title generation has no AgentRun, so its existing generation-event ownership stores a
separate durable title-operation snapshot containing the frozen Lightweight chain and cursor. Quota
renews Workspace cooldown and advances before the title retry policy. Non-quota failures retain the
existing title retry policy. The current structured-output-to-plain-text compatibility transition is
candidate-local envelope handling, not candidate progression. Title chain exhaustion retains the
deterministic initial title and never fails the foreground Run.

Every operation preserves semantic label intent. Incompatibility skips without provider call or
cooldown. Background quota failures update shared cooldown but never mutate foreground Session
profile or Primary reservation. Provider, Redis, broker, and filesystem I/O remain outside database
transactions, and SDK automatic retry remains disabled.

**Rejected alternatives:**

- Exhausting generic retry before fallback was rejected because it contradicts immediate quota
  progression.
- Sharing one mutable operation slot between compaction and sampling was rejected because one
  operation could erase the other's recovery state.
- Forcing title generation into an AgentRun was rejected because it would couple best-effort title
  ownership to foreground failure and terminal lifecycle.
- Keeping title cursor only in memory or excluding background quota from cooldown was rejected
  because restart could repeat quota candidates or split physical availability authority.

**Risks:**

- Quota interception must occur before retry publication and terminal finalization while preserving
  User Stop precedence and failed-partial discard.
- Compaction plan rebuild and candidate progression must remain separate so stale summaries cannot
  commit.
- Title envelope fallback, same-candidate retry, and cross-candidate progression require distinct
  counters and diagnostics.

### model-260912/ADR-D7: Store bounded applied-route provenance and require deterministic E2E evidence

**Affected requirements:** `model-260912/REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-8`

**Accepted on:** 2026-09-12 by the delegated autonomous technical decision owner.

Every successful physical model call stores bounded applied-route provenance with the durable turn
marker: requested semantic label, operation identity/kind, candidate ordinal and
`primary | fallback` role, exact provider/integration/model identity, public display name, and the
existing allowlisted applied limits/settings. Historical presentation reads this immutable record
instead of current Agent configuration. Assistant response content remains unchanged; the Context
inspector or another explicit details surface may display the route.

Each active operation stores exactly one bounded mutable/final outcome record per candidate, so the
operation retains at most five records. A record progresses from `pending` to `active` and then to
one final state such as `succeeded`, `quota_or_billing`, `cooldown`, `probe_busy`, or `incompatible`.
Chain exhaustion is an operation-level terminal code rather than a sixth candidate record. Records
retain candidate ordinal, bounded safe identity/display, database timestamp, and typed reason only.
Foreground exhaustion links this summary to existing failed-run terminal metadata. Title exhaustion
retains the deterministic title and emits only structured diagnostics.

Metrics use low-cardinality operation-kind, provider-family, candidate-role, transition, result, and
reason labels. Workspace, Session, integration, and model identifiers are correlation fields in
bounded structured logs, not metric labels. Raw provider payloads, prompts, output, credentials, and
arbitrary diagnostics are excluded. Re-entry of an already quota-attempted identity is rejected
before provider call and emits an invariant counter/log.

Required acceptance evidence is credential-free E2E against a deterministic model-provider fake
that can script outcomes by integration/model and expose explicit attempt barriers. Database-time
control or deadline mutation verifies cooldowns and leases; fixed sleeps do not establish ordering.
The matrix covers chain migration/CRUD, main fallback, compatibility skip, rate-limit separation,
candidate non-repetition, cross-Session cooldown, concurrent half-open claims, crash/lease recovery,
worker handover, Stop/manual retry, reservation lifecycle, compaction, title, exhaustion,
provenance, Redis-empty recovery, desktop Composer/picker, and mobile bottom-sheet behavior. Unit
and repository tests support but do not replace the required E2E evidence. Live credentials are
optional diagnostics only.

**Rejected alternatives:**

- Deriving historical route from current Agent settings was rejected because reorder or model
  replacement would rewrite the meaning of past work.
- High-cardinality metrics were rejected because candidate identities would create unbounded metric
  series.
- Provider live-quota tests were rejected as required evidence because they are nondeterministic,
  credential-bearing, and cannot reliably force the concurrency and recovery states.

**Risks:**

- Public terminal summaries must stay bounded and user-safe even when every candidate has a distinct
  reason.
- The deterministic provider fake needs explicit attempt/barrier evidence without becoming a second
  product behavior implementation.

## Consequences

- Agent and Workspace configuration, public v1 schemas, generated clients, and Web forms move to one
  nested label/candidate model.
- AgentRun gains bounded foreground and compaction routing state; automatic title owns a separate
  generation-scoped routing snapshot.
- PostgreSQL becomes the short-lived Workspace cooldown, reservation, and probe-fencing authority;
  Redis remains optional invalidation/coordination.
- Quota failures bypass same-candidate generic retry, while all other failure categories preserve
  current retry ownership.
- Composer availability is a DB-derived projection. Assistant response content remains unchanged and
  durable provenance moves to explicit details.
- The coordinated release is a public v1 breaking change and requires regenerated clients plus
  release notes.

## Risks

- The design spans Agent/Workspace configuration, Session/Run recovery, auxiliary model operations,
  public APIs, generated clients, Web state, and testenv; partial rollout is not coherent.
- PostgreSQL claim transitions must stay short and fenced to avoid a hot candidate becoming a broad
  lock bottleneck.
- Ambiguous process loss before a normalized provider outcome is durably recorded retains the current
  unknown-attempt recovery behavior; it cannot be inferred as quota.
- Availability invalidation can be delayed when Redis/WebSocket publication fails, so every UI read
  must converge through authoritative REST/DB state.
- Actual user discoverability and manual-recovery reduction remain post-release validation risks.
