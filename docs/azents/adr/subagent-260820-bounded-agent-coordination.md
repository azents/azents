---
title: "Bounded Subagent Coordination"
created: 2026-08-20
updated: 2026-08-20
tags: [agent, subagent, engine, architecture]
document_role: primary
document_type: adr
snapshot_id: subagent-260820
---

# Bounded Subagent Coordination

- Snapshot: `subagent-260820`
- Document reference: `subagent-260820/ADR`
- Requirements:
  [`subagent-260820/REQ`](../requirements/subagent-260820-bounded-agent-coordination.md)

## Context

The model-facing `list_agents` tool currently queries every durable
`SessionAgent` in the current root tree and returns the complete retained history.
The same durable tree is also the canonical source for user-facing Subagent Tree
history, canonical path targeting, terminal-result observation, and follow-up reuse.
As a result, the coordination-tool payload grows for the full root-session
lifetime even though active work is bounded.

Azents does not retain a continuously loaded subagent thread comparable to Codex
V2's in-process resident thread. A child `AgentSession` is durable, and each new
Run is admitted and executed through the ordinary worker and mailbox path.
Model-visible coordination membership can therefore be bounded either by adding a
new durable membership lifecycle or by projecting a bounded set from existing
durable execution, mailbox, and interaction state.

The current tool result also exposes local `agent_name`, canonical `agent_path`,
projected `agent_status`, and unbounded `last_task_message`. The web known-tool
renderer treats all four fields as required. Current Codex V2 instead uses the
canonical path as `agent_name` and returns only `agent_name` plus `agent_status`.

## Decision Map

### Fixed or derived outcomes

- The complete `SessionAgent` tree and every linked child `AgentSession` remain
  durable and reusable.
- `list_agents` includes the root plus every child with active execution or
  wake-producing collaboration input.
- When configured capacity is reduced below existing active work, the temporary
  effective bound expands to the active count, new activation remains blocked, and
  the result contracts as active work finishes.
- An omitted historical child remains targetable by canonical path and
  `followup_task` continues in the same child `AgentSession`.
- Terminal-result delivery, parent observation cursors, and the complete
  user-facing Subagent Tree remain independent of model-facing list membership.
- No model-facing close/resume operation or new user-configurable capacity is
  added.
- Correctness does not depend on Redis availability or persistence.

### Pending material decisions

- [x] `subagent-260820/ADR-D1`: derive bounded model-facing coordination
  membership deterministically from existing durable authority.
- [x] `subagent-260820/ADR-D2`: fill unused coordination slots with the most
  recently active inactive historical agents.
- [x] `subagent-260820/ADR-D3`: return only canonical `agent_name` and bounded
  `agent_status` for each listed agent.

### Agent-owned implementation categories

- Repository and service type names after ownership is decided.
- Query helper boundaries, SQL constraint/index names, and stable ordering
  tie-breakers.
- Equivalent local batching and projection helpers that add no new state,
  contract, lifecycle, or mode.
- Test fixture identifiers, logging field names, known-tool renderer component
  boundaries, and documentation cross-reference wording.

## subagent-260820/ADR-D1. Derive coordination membership from existing durable authority

`list_agents` derives its bounded membership on every call from PostgreSQL-backed
root-tree state. It does not persist a separate resident, loaded, open, evicted, or
closed lifecycle for `SessionAgent`.

The required coordination set is the root plus every child whose linked
`AgentSession`, latest `AgentRun`, or wake-producing mailbox state indicates active
work. The result capacity is the current Agent `max_subagents`, except that an
already-active count above a newly lowered setting temporarily becomes the
effective capacity until those Runs finish. New spawn and inactive-target
activation remain blocked by the lowered setting under the existing admission
contract.

Any inactive historical candidates admitted by `subagent-260820/ADR-D2` are a
read-time projection from existing durable interaction evidence. Selection creates
no membership write, eviction event, shutdown, archive, or broker signal.
Canonical path resolution continues to use the complete durable `SessionAgent`
tree, so omission from `list_agents` has no effect on targeting or follow-up reuse.

The projection uses one database transaction to read the current root tree,
sessions, latest Runs, and required mailbox evidence. Stable query batching,
tie-breakers, and helper boundaries are implementation details as long as the
result is deterministic for the same authoritative state.

### Rejected alternatives

- **Persist explicit resident membership:** Azents has no continuously loaded
  subagent compute object for such a lifecycle to own. New membership columns and
  activation/eviction writes would duplicate Run and mailbox authority, require a
  migration and recovery protocol, and introduce drift without satisfying an
  additional Requirement.
- **Keep membership only in worker memory or Redis:** process loss would change the
  model-visible list, and Redis availability or persistence cannot be correctness
  authority.

## subagent-260820/ADR-D2. Fill unused slots with recently active historical agents

After selecting the required root and active/wake-producing child set, `list_agents`
fills any remaining child capacity with inactive historical agents ordered by
their latest durable agent-to-agent interaction time. Spawn assignments,
`send_message`, `followup_task`, and terminal-result delivery already update
`SessionAgent.last_message_at`, so the projection reuses existing collaboration
activity rather than introducing a separate LRU clock.

The child capacity is the effective capacity defined by
`subagent-260820/REQ-1`. Required active children consume capacity first. If
configured capacity was lowered below the active count, no inactive child is
included until active work contracts below the configured value. Otherwise, the
remaining slots select the newest inactive children. Stable fallback ordering for
equal or missing activity timestamps is an implementation detail.

Unread terminal results do not pin a child in the model-facing list. Durable parent
mailbox delivery and the user-facing unread projection remain the authoritative
result-observation mechanisms. Terminal delivery updates interaction activity, so
a newly completed child is naturally recent without creating a second unread-based
membership authority.

### Rejected alternatives

- **List active children only:** this minimizes the payload but removes a child
  immediately after completion, making ordinary follow-up discovery less useful
  than the accepted Codex-like bounded recent set.
- **Pin every unread terminal child:** the unread backlog can exceed available
  capacity and would compete with current coordination. Mailbox delivery already
  owns unread-result correctness.

## subagent-260820/ADR-D3. Use the canonical two-field Codex list contract

Each `list_agents` entry contains exactly:

- `agent_name`: the canonical absolute `SessionAgent.path`, including `/root` for
  the root; and
- `agent_status`: the existing bounded projected status string.

The current local-name interpretation of `agent_name`, duplicate `agent_path`, and
unbounded `last_task_message` fields are removed together. The model receives one
canonical identity field and no delegated task or message content through the
coordination list.

The azents-web known-tool parser and specialized `list_agents` renderer change in
the same delivery boundary. The collapsed row continues to show the listed count.
Expanded rows use canonical `agent_name` as the item title and `agent_status` as
the status detail, with no task-preview content. Malformed or old-shaped results
continue to use the existing call-local Generic fallback; the backend does not emit
a legacy dual shape or compatibility fields.

This is a model-facing built-in tool result rather than a public REST API or
generated-client contract. Existing durable Subagent Tree API fields, including
local name, canonical path, latest task, terminal message, and unread state, remain
unchanged.

### Rejected alternatives

- **Keep local `agent_name` plus canonical `agent_path`:** this retains duplicate
  identity and diverges from the current Codex contract without satisfying another
  consumer requirement.
- **Keep and truncate `last_task_message`:** a fixed truncation would bound bytes
  but would continue mixing user-facing historical preview responsibility into the
  model coordination tool.
