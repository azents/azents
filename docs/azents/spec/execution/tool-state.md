---
title: "Toolkit State and execution binding"
created: 2026-11-04
tags: [wiki]
---

# Toolkit State and execution binding

Owns durable private Toolkit state, execution-owner binding and completed database operation boundaries. State namespaces do not imply broad ownership fences over every external operation.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Toolkits](../domain/toolkit.md)
- [Goals and Session Todos](../automation/goals.md)
- [Tool discovery and working sets](../tools/discovery.md)
- [Memory](../domain/memory.md)

## Execution binding and repository state boundaries

Ordinary Toolkit/Agent management authorization uses scoped reads without
parent/admin read locks. Durable namespace claim is separate: shared slug change
and attachment coordinate only their actual Toolkit allocation, and missing or
changed reservations allocate under the exact Agent/sequence identity claim.
Reuse of an already-valid reservation is an ordinary read and does not acquire
that Agent allocation fence. Concurrent different Toolkits with the same base
slug retain distinct durable executable namespaces.

Resolved Session Toolkits bind a narrow PostgreSQL execution owner
(`session_id`, `owner_generation`) before Toolkit lifecycle entry. This covers
execution identity and actual effect admission, not every private state scope.
Request-local full resource authority may change between Runs under the same owner,
while the durable owner token remains fixed; reusing a Toolkit under another
generation is rejected. Idle-continuation Toolkit preparation uses the same narrow
binding before entry.

Todo/Goal payloads, Skill adoption, GitHub selection, MCP/AWS/GCP snapshots and
instruction appendix dedupe use ordinary completed operations without generic
root-tree ownership manager binding. Existing state CAS and source/schema
identity remain. Memory content mutation, durable Goal events, Run VFS publication,
Memory boundary publication and Scheduled terminal publication explicitly fence
only their critical exact Session mutation groups. External discovery, Runtime/
file reads, provider calls and broker publication occur outside database scopes.
Observed stale admission and critical-owner rejection retain their existing
failure handling; no row lock is held across external I/O.

Tool Search working-set, AGENTS.md/Claude Rules appendix dedupe, and Todo payload
models are pure core state. Their ordinary reads and mutations are completed
repository operations; the successful compaction reset uses the same repository
mutation inside the compactor's atomic database composition.

Raw MCP, AWS, GCP, and GitHub MCP tool snapshots plus the GitHub selected
installation are also pure core state loaded and replaced through completed
repository operations. External tool discovery, credential exchange, and tool
execution remain outside those operations. Successful snapshot replacement keeps
the existing optimistic retry without a Session root fence; runtime still validates
the stored server/project identity before rebuilding tools.

Saved snapshot and GitHub selection descriptions load through independent,
database-enforced read-only scopes. Their private metadata replacements use
ordinary write scopes with existing state version predicates. Neither path
acquires a generic Session ownership fence or requires a globally latest view. Missing
state remains an absent description; retained source identity and schema/executor
pairing remain mandatory.

Runtime Toolkit availability uses the captured capability projection rather than
current-operation admission. Retained Runtime/configuration, ready Runner,
Runner-reported workspace and existing BOUND Session-folder evidence describe
availability without Runtime reconciliation, start, pending-folder binding or
Agent/context row locks. Dynamic Worktree preparation shares one retained
eligibility projection for create and remove; removal additionally requires a
ready managed allocation. Actual tool invocation still revalidates current
capability, expected configuration/target, binding and ownership before external
effects. Model preparation uses a nonlocking current-owner observation rather
than a generic root/Agent/ancestor gate. Critical persisted outputs separately
exclude handover through the exact Session mutation commit; no short owner check
promises exclusion throughout external execution.

Team and private User Sessions share canonical execution authority. Generic Toolkit, resolve, run,
and turn contexts contain Workspace, Agent, Session, Run and resource authority, but no execution
User identity. The runtime never infers a User from a message sender, public requester, broker wake-up,
Agent creator, Workspace owner, viewer, approver, uploader, or fallback.

Session-managed Toolkit instances are keyed by stable source identity and revision, not a Human
identity. Therefore a different authorized requester, External Channel invocation, recovery,
continuation, or subagent delivery reconciles the same Team-scoped Toolkit lifecycle. Workspace
Toolkit configuration, Agent attachments, toolkit-level OAuth, Workspace LLM integrations, Runtime
tools, and Session/Run capabilities remain available without a User. Authenticated management and
OAuth setup remain requester-authorized operations and do not leak their requester into runtime
contexts. User-brought credentials are not a Team capability.

Runtime Web is an auto-bound Toolkit available only while the Agent has managed
Runtime capability. Root Agents and subagents receive exactly request, list, and
close tools over the Agent-owned service set. Request creates a missing numeric-port
service in the Off state or returns the existing service unchanged; list returns
bounded content-free service projections; close idempotently turns one service Off.
The Toolkit cannot turn a service On, reset or extend expiration, update metadata,
delete a service, control the application process, expose browser authentication
material, or access another Agent's services.

## Durable Toolkit State

Toolkit State is a common storage model where a toolkit can store durable JSON state bound to one AgentSession. Side state that does not need a separate relation model but must persist between turns is stored in the `toolkit_states` table.

Identity is always session-bound and is the combination of `agent_id`, `session_id`, `toolkit_namespace`, and `state_name`. `session_id` is required. Stored payload consists of `state_json`, `schema_version`, and optimistic-lock `version`.

Runtime abstraction is `ToolkitStateStore` and typed `ToolkitStateHandle`. `load(default_factory)` returns default if row is missing. `save(state)` performs whole-state replace. `update(default_factory, mutator)` reads latest state, applies the mutator, and retries on optimistic lock conflict.

External Channel uses the same storage model through a domain-specific typed store.
Each binding owns exactly one identity in namespace `external_channel` with state name
`channel_work:{binding_id}`. The schema-version-5 payload contains the current or
latest Channel Work cycle, nullable Slack status anchor and initiator, binding-scoped
awaiting Run identity, and ordered current provider projection parts. Each projection
part records its current provider identity, outcome status, desired revision, and
`standalone | reply` Tracker host kind. It preserves a stable `work_cycle_id`, validates
the binding-derived identity, and uses independent whole-state optimistic concurrency
per binding.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/repos/toolkit_state`](../../../../python/apps/azents/src/azents/repos/toolkit_state)
- [`python/apps/azents/src/azents/engine/tools`](../../../../python/apps/azents/src/azents/engine/tools)
- [`python/apps/azents/src/azents/repos/session_execution`](../../../../python/apps/azents/src/azents/repos/session_execution)
