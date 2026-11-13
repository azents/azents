---
title: "Work continuity across execution segments decisions"
created: 2026-11-13
tags: [backend, engine, continuation]
document_role: primary
document_type: adr
snapshot_id: continuation-261113
---

# Work continuity across execution segments decisions

- Snapshot: `continuation-261113`
- Requirements: [continuation-261113/REQ](../requirements/continuation-261113-work-continuity.md)

## D1. Separate admitted work references from execution-segment ownership

- Authority: the requester explicitly selected separation of work and AgentRun for every continuation kind, then requested implementation.
- Requirements: REQ-1 through REQ-5.

Logical obligations retain their existing canonical domain identity and state. The execution engine carries an explicit, common snapshot of admitted work references through execution changes. An individual Run is an execution segment and an audit/ordering identity, not the identity or exclusive current host of a Scheduled Task cycle or Routine occurrence. Session ownership fencing, active execution checks, exact admitted references and canonical domain-state validation remain required.

Goal and Channel Work already have independent canonical Session/work-cycle state. Preserve those semantics; do not introduce another lifecycle or duplicate authority merely to make their data shape match Scheduled Tasks and Routines. Their continuation paths participate in common context propagation.

### Rejected alternatives

- Copy Scheduled Task and Routine host IDs after each special action: retains domain-specific handoff coupling and repeats the class of defect for future continuation paths.
- Accept any active work in the same Session: does not establish that the consuming execution actually received that work.
- Replace all work types with a generic workflow lifecycle: changes independent completion and notification contracts beyond the request.
- Remove execution ownership and predecessor ordering checks: work independence does not authorize stale Workers or overlapping action continuations.

### Consequences

- Work context is authoritative server-maintained execution input, not model-supplied text or a compacted summary.
- A context can contain several independent occurrences. Completion removes only the selected obligation's active state and does not finish unrelated work.
- Domain `current_run_id` and the special Run scheduled-cycle binding cease to determine work authority; lifecycle/preservation paths use explicit work association and actual execution status.
- Storage transition must retain existing admitted work and provenance, then remove the obsolete representation rather than retaining an ongoing fallback.
- Run and operation IDs remain for audit, execution fencing, duplicate delivery and predecessor completion.

No separate scheduling mode, generic task product, or operational rollout is authorized by this decision.

## D2. Expose exact work identities and select them explicitly

- Authority: the requester approved the presented explicit occurrence-ID approach, including continuation exposure and spec-correct compaction handling, then extended the same principle to analogous tools.
- Requirements: REQ-2, REQ-3, REQ-6, REQ-7.

Scheduled completion identifies an exact cycle rather than deriving one implicitly from the current Run. Model-facing initial and continuation inputs expose that server-issued identity beside its title and scheduled instant. Several admitted cycles may coexist in the common work context without overwriting each other or forcing one-cycle-per-Run execution sequencing.

Apply the same exact-work principle to analogous progress/completion operations. Routine retains its explicit occurrence identity. Goal and Channel Work must distinguish the existing logical item/cycle from any later replacement without changing their existing single/multiple-item policies. Creation and completion remain distinct operations; knowing an identifier is never standalone mutation authority.

The established compaction summary-enrichment pipeline preserves model-facing work identities in the relevant server-authored snapshots. This deliberately supersedes the old Scheduled compaction rule that omitted cycle IDs; it does not expose Run, lease or provider-message identities. Keep fail-open hook behavior, continuity-last ordering, fixed-plan owner/head/tail validation and atomic summary/head settlement. Neither a model-generated summary nor a failed/stale compaction creates work authority. Existing model-request Toolkit preparation may supply the current bounded work context, but no new compaction mode or hidden raw-tail mechanism is introduced.

### Rejected alternative

Consuming only one Scheduled occurrence per Run would preserve an implicit tool selector, but would unnecessarily make execution segmentation determine which independent logical item can be handled. The requester selected explicit identity instead.

### Consequences

- Tool schemas, model-visible renderers and runtime validation change together; adding an ID argument while keeping the ID hidden is incomplete.
- Continuation and compaction IDs are exact server-owned data, never aliases inferred from titles or model text.
- Parallel/recovered completion must resolve each exact call's durable occurrence result independently; one committed result cannot mark another occurrence's uncommitted call successful.
- Analogous tool identity changes require their own actual domain admission/preservation evidence, not mechanical copying of Scheduled fields.
