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
