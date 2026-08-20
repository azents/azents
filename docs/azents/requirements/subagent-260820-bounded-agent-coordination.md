---
title: "Bounded Subagent Coordination Requirements"
created: 2026-08-20
updated: 2026-08-20
implemented: 2026-08-20
tags: [agent, subagent, engine]
document_role: primary
document_type: requirements
snapshot_id: subagent-260820
---

# Bounded Subagent Coordination Requirements

- Snapshot: `subagent-260820`
- Document reference: `subagent-260820/REQ`

## Problem

The model-facing subagent coordination list currently grows with every retained
subagent in a root session. Long-running sessions therefore spend increasing
context on agents that are no longer relevant to current coordination, even
though the product must retain their history and identity.

## Primary Actor

An active root or subagent coordinating work through the subagent collaboration
tools.

## Primary Scenario

During a long-running root session, the active agent creates and completes more
subagents than can work concurrently. When it inspects the agent list, it receives
a complete but bounded view of the agents relevant to current coordination. If it
later assigns follow-up work to an omitted historical subagent by canonical path,
that subagent continues in its existing session and context rather than becoming a
new identity.

## Supporting Scenarios

- A parent receives and observes a child's terminal result even when that child is
  no longer present in the model-facing coordination list.
- An administrator lowers the configured subagent capacity while a root session
  already has more active children than the new value.
- A user inspects the complete durable subagent tree, including historical agents,
  terminal results, and unread-result state.
- A coordination operation that targets an existing canonical agent path preserves
  the existing capacity and lifecycle constraints.

## Goals

- Keep the model-facing agent list bounded for the lifetime of a root session.
- Preserve a complete view of agents that currently require coordination.
- Preserve durable subagent identity, transcript history, and follow-up reuse.
- Preserve terminal-result delivery and the complete user-facing subagent tree.
- Bound each listed agent entry independently of delegated task or message length.

## Non-Goals

- Deleting, archiving, or applying retention to historical subagent sessions.
- Adding a model-facing close or resume operation.
- Changing the configured active-subagent concurrency or maximum tree depth.
- Replacing or truncating the user-facing complete Subagent Tree.
- Changing subagent canonical path identity.

## Requirements

### REQ-1. Bounded coordination list

The model-facing agent list must have a fixed maximum size derived from the
effective subagent coordination capacity, regardless of how many historical
subagents the root session retains. When an administrator lowers the configured
capacity below already-active work, the effective capacity temporarily expands to
the existing active count and contracts to the configured value as that work
finishes.

**Acceptance criteria**

- Repeatedly creating and completing subagents does not cause the maximum
  `list_agents` result count to grow beyond the root plus the configured subagent
  capacity during normal operation.
- If the configured capacity is lowered below the existing active count, every
  existing active child remains listed and no new child activation is admitted
  until the active count falls below the configured value.
- The temporary result bound during that convergence period is the root plus the
  existing active count; inactive historical children do not expand it further.
- The result bound remains valid for calls made by the root and by descendant
  subagents.

### REQ-2. Complete current coordination view

The bounded list must include every agent in the current root tree that has active
execution or wake-producing work requiring coordination.

**Acceptance criteria**

- Every child with a running or pending run is listed.
- Every child with pending wake-producing collaboration input is listed.
- The root agent remains listed.
- Historical terminal agents may be omitted only when doing so does not hide
  active or wake-producing work.

### REQ-3. Durable historical reuse

An existing historical subagent omitted from the bounded list must remain
addressable through its canonical path and reusable for later work.

**Acceptance criteria**

- Follow-up work addressed to an omitted historical path continues in the same
  child AgentSession and transcript.
- Reuse does not create a replacement SessionAgent identity or a duplicate sibling
  path.
- If all configured capacity is occupied by active work, the existing capacity
  rejection behavior remains authoritative.

### REQ-4. Terminal-result safety

Reducing the model-facing list must not lose, duplicate, or suppress terminal
results from subagents.

**Acceptance criteria**

- An eligible terminal result is durably delivered to the direct parent exactly
  once under the existing delivery contract.
- The parent's unread-result state remains accurate until the result is observed.
- Omitting a terminal agent from `list_agents` does not remove its terminal result
  or transcript history.

### REQ-5. Bounded entry payload

Each model-facing agent-list entry must contain only bounded coordination metadata
and must not scale with delegated task or message content.

**Acceptance criteria**

- Arbitrarily long delegated tasks or agent-to-agent messages do not increase an
  individual list entry beyond fixed coordination fields.
- The entry still identifies the agent canonically and communicates its projected
  coordination status.

### REQ-6. Complete user-facing history

Users must retain access to the complete durable subagent tree independently of
the bounded model-facing list.

**Acceptance criteria**

- The Subagent Tree continues to expose historical and current SessionAgent nodes.
- Existing terminal message, latest-task preview, activity ordering, and unread
  result projections remain available to user-facing consumers.
- Model-facing list omission does not delete or hide the corresponding node from
  the complete Subagent Tree.

## Fixed Constraints

- `SessionAgent` remains the durable canonical tree and path identity source.
- `AgentSession` remains the transcript, Run, mailbox, and continuation boundary.
- Completed subagents remain reusable through their existing child AgentSession.
- Lowering the configured subagent capacity does not interrupt or hide already
  active work; it blocks new activation until the tree converges to the new value.
- Terminal-result delivery remains durable and idempotent through the direct
  parent's mailbox.
- Redis availability or persistence must not be required for correctness.

## Open Assumptions

- No new user-configurable capacity setting is required; the existing subagent
  coordination capacity can define the list bound.

## Confirmation

Confirmed by the requester on 2026-08-20, including the existing-active-work
convergence policy, before ADR and design decisions began.
