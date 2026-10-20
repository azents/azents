---
title: "Testable Agent Deletion Lifecycle Decisions"
created: 2026-10-20
tags: [agent, lifecycle, backend, testing]
document_role: primary
document_type: adr
snapshot_id: harbor-261020
---

# Testable Agent Deletion Lifecycle Decisions

- Snapshot: `harbor-261020`
- Requirements: `harbor-261020/REQ-1` through `harbor-261020/REQ-7`, confirmed on 2026-10-20.
- Mode: Autonomous technical decisions, explicitly delegated by the requester on
  2026-10-20. The primary agent records decisions with one dedicated technical
  interviewee. Final Design approval remains with the requester.

## Fixed Outcomes

- Retain asynchronous decommission admission, Session retention/purge ownership,
  current-attempt lease fencing, and current-generation Runtime deletion acknowledgement.
- Cleanup responsibilities and dependency completeness must be independently testable.
- Preserve shared resources and retained historical evidence.
- Keep current schema and dependency ownership in Living Specs, maintained by the
  backend-scoped convention.
- Do not introduce new product configuration, user controls, or versioning.

## Material Decision Map

| Topic | State | Decision owner |
| --- | --- | --- |
| Agent-specific composition versus a generalized Session-and-Agent lifecycle engine | Accepted: Agent-specific composition | Delegated technical interviewee and primary agent |
| Participant continuation through new durable checkpoints versus replay using existing resource evidence | Accepted: replay native evidence | Delegated technical interviewee and primary agent |
| Field-scoped restrictive provenance and creation references | Verified existing contracts; no additional FK removal | Delegated technical interviewee and primary agent |

Local identifiers, dependency injection wiring, equivalent pure data structures, and
fixture names remain implementation details rather than separate approval topics.

## ADR-D1. Lifecycle Reuse Boundary

**Question:** Should this change generalize the existing Session lifecycle engine, or
introduce an Agent-specific participant composition that reuses neutral schema facts
and applicable validation mechanisms?

**Evidence**

- Session participants expose archive/restore policies and purge phase checkpoints.
- Agent decommission already delegates Session destruction to retention purge and has
  its own durable job, lease/attempt, and terminal Runtime generation authority.
- Agent cleanup currently lacks equivalent explicit ownership/dependency composition.

**Options**

1. Generalize both Session and Agent orchestration in this change. This offers one
   reusable engine but expands the cutover and regression boundary to existing Session
   archive, restore, and purge behavior.
2. Compose Agent-specific executable cleanup participants and reuse neutral PostgreSQL
   schema facts and applicable ownership validation. This keeps Session authority
   unchanged, but requires clear boundaries to prevent duplicated generic graph logic.

**Recommendation:** Option 2, keeping the requested Agent deletion change bounded while
making resource ownership and participant tests explicit. This does not authorize a
second Session destruction path or a second manually maintained ownership list.

**Decision:** Accept option 2 on 2026-10-20 under delegated technical authority.
Keep Agent participant execution separate from Session archive/restore/purge policies.
Reuse neutral PostgreSQL catalog evidence and pure graph operations where semantically
equivalent. Preserve Session-owned destruction and all existing Agent finalization gates.

**Consequences:** This bounds the cutover to Agent deletion. Shared schema utilities may
be factored without changing Session behavior; Agent RESTRICT/NO ACTION blocker coverage
must be explicit rather than treating Session mutating-path validation as sufficient.

## ADR-D2. Participant Continuation Evidence

**Question:** Does each Agent cleanup participant require a new durable checkpoint, or
can the coordinator safely replay participants using current job phases and existing
resource-specific idempotency evidence?

**Options**

1. New participant execution checkpoints. They improve per-participant continuation and
   durable progress attribution, but add schema, existing-job adoption, and checkpoint
   fencing obligations.
2. Deterministic participant replay with existing durable resource evidence. This avoids
   a second progress ledger, but each external operation must prove replay safety and
   repeated work remains possible after a crash.

**Decision:** Accept option 2 on 2026-10-20 under delegated technical authority.
Keep existing job states, attempts, retry scheduling, and resource-owned evidence.
Introduce no participant execution table, snapshot, policy version, or adoption
migration. Independently testable participant contracts do not require new persistence.

**Required constraints**

- Re-run current finalization predicates in the final locked DB transaction.
- Fence every Agent-owned DB mutation with the job ID, Agent ID, lease owner, and
  expected attempt in its own transaction. This closes existing gaps in blob completion,
  final external cleanup, and stop-only retirement; it is not a claim those operations
  already carry complete fencing.
- Use immutable scoped external targets and existing idempotent APIs. A lease change
  can overlap old external I/O; reject its stale DB completion rather than promise
  exactly-once effects.
- Current-avatar cleanup success covers only the captured immutable key set in the
  current attempt. Finalization rechecks the current avatar target identity.
- Attribute failures to the participant and phase through existing job error fields and
  structured logger context.

**Channel boundary:** Native binding/Work termination is the existing durable
completion authority. Leave-presence and Tracker provider effects remain existing
best-effort post-commit effects. The current code returns detached effect plans and
does not guarantee recovery of every plan after a crash. This decision introduces no
outbox or stronger provider-delivery guarantee. A generic participant checkpoint alone
would not fix that separate credential/effect-lifetime problem.

**Consequences:** Existing jobs resume from native state without backfill. Successful
idempotent operations may be repeated after a crash; tests must prove this is safe.
Session purge and Runtime generation acknowledgements remain the authorities, not a
generic participant-complete marker.

## ADR-D3. Preserve Verified Scoped References

**Decision:** Keep `exchange_files.source_agent_id` and
`chat_write_requests.creation_agent_id` restrictive FKs. No further FK-removal migration
is justified by the verified reachable creators. This is a bounded preservation
decision under REQ-1 and REQ-5, not an authorization to broaden destructive cleanup.

**Evidence:** ExchangeFile publication derives source Agent identity from the same
canonical owner for Agent/Tool/Provider provenance; Human/preview rows use null source
Agent identity. Object-copy paths construct destination-owned metadata rather than
clone foreign Agent provenance. Session creation writes creation requests against the
same Agent and newly created Session; native Session CASCADE removes those records.

**Consequences:** Classify both table and ordered column identities. Extend the neutral
PostgreSQL FK facts with source/referenced columns so the catalog distinguishes these
edges. Final verification checks both ExchangeFile references and creation requests.
Unexpected cross-scope rows block finalization with attributable diagnostics; they are
not deleted or detached to make cleanup pass. Tests prove supported creator invariants
and preservation of deliberately mismatched rows. No production-data invariant is
claimed without inspecting production; invalid legacy/manual data is a residual risk.

## ADR-D4. Deleting Visibility, Read-only Enforcement, and Failure Attribution

The requester explicitly added REQ-8 and REQ-9 after endorsing the previous design
direction. This decision extends that scope with deletion badges, authoritative
read-only behavior, and one internal failure identifier. It supersedes the earlier
no-public-change/no-job-schema-change boundary only for these requested outcomes.
The no-participant-ledger, no-versioning, and unchanged retry-cadence decisions remain.

**Decision:** Accept the following on 2026-10-20 under delegated technical authority.

- Add a required nullable `deletion_status` projection to Agent list/detail responses:
  null for active Agents, `deleting`, or `deletion_error`. Derive it from the canonical
  lifecycle and job evidence in the authorized read boundary; batch job lookup for lists.
- Both non-null states imply read-only presentation. The server enforces read-only
  from lifecycle, not the cached response or `enabled`, using an active-Agent lock/CAS
  in each user-originated Agent-scoped mutation transaction. Existing authorization
  remains first; return a safe `agent_decommissioning` conflict for authorized writes.
- Revalidate long-running upload/OAuth publication at its durable attachment commit.
  Previously started external I/O may overlap deletion; it cannot attach new Agent
  resources after deletion wins the commit race. Internal lifecycle/native cleanup
  retains explicit authority; no public or generic bypass flag is added.
- Preserve authorized idempotent DELETE. Do not add cancel/force-delete/manual-retry
  controls or change other Agents' or shared-resource authority.
- Add nullable `failure_boundary_key` to the existing decommission job. It names the
  first unresolved participant/phase failure and is not a cleanup checkpoint. Keep
  bounded error diagnostics internal. Claim/reclaim must not clear the failure merely
  because another attempt starts.
- Only current-owner/attempt successful proof of the exact failed responsibility clears
  its key and associated diagnostics atomically. Earlier success, an unrelated wait,
  cancellation, or stale ownership cannot clear it. A second earlier failure keeps the
  first unresolved boundary; finalization clears it atomically with completion. Stable
  boundary keys cover participant and final verification errors without policy versions.
- Represent expected retention, active-work stopping, and Runtime-ack waits as typed
  outcomes rather than exceptions. Use the existing scheduling/backoff behavior without
  setting or clearing an unrelated failure. Existing non-gating channel provider effects
  do not become new failure-label triggers.

**Alternatives rejected:** UI-only disabled controls do not protect direct or stale API
requests. Inferring state from `enabled` confuses independent concepts. Publishing raw
job errors leaks operational details. Reusing exception names/summary text as encoded
recovery authority cannot identify the failed responsibility. Generic participant
checkpoints are unnecessary for one unresolved-failure identifier.

**Compatibility:** Generate an additive nullable-column migration. Existing jobs retain
phase, attempt, timing and diagnostic text, with no invented failure boundary. Legacy
`RuntimeError` records may be ordinary waits, so do not regex-classify their cause.
Null boundary plus retained diagnostic evidence is a typed internal unattributed
previous-error condition and conservatively projects `deletion_error`. This reports
recorded prior error evidence, not a newly classified failure of the current wait.
Do not invent historical participant ownership. Unknown prior obligations clear only
after complete successful required final verification/root completion; a later known
failure cannot replace them with an easier recovery condition. Known-boundary recovery
clears its diagnostics too, so it cannot be mistaken for unknown legacy evidence.
Older expected waits may consequently retain a previous-error indicator until deletion
completes; this historical ambiguity is an explicit compatibility limitation.
A decommissioning Agent missing its required job is an invariant error and stays
read-only with a safe error projection. No raw key, SQL, exception text, credential, or
internal job identifier is returned through the new field.

**UI and validation:** Use one localized status component on lists and desktop/mobile
Agent headers. Keep inspection navigation enabled and modifying controls disabled or
absent. Shared error copy is neutral: deletion encountered an error and changes remain
unavailable. Do not promise automatic retry from this projection alone: a missing-job
invariant error has no job to claim. Existing valid jobs retain native automatic retries.
Refresh visible deleting Agents through existing query refetch/invalidation; server
conflict refreshes stale pages. Unit/DB/component tests own the state, recovery,
permission, and mutation-race matrix; representative E2E remains thin.
