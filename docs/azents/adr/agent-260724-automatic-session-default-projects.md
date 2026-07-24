---
title: "Agent Default Projects for Automatic Sessions"
created: 2026-07-24
tags: [agent, session, workspace, project, architecture]
document_role: primary
document_type: adr
snapshot_id: agent-260724
---

# Agent Default Projects for Automatic Sessions

- Snapshot: `agent-260724`
- Requirements: [`agent-260724/REQ`](../requirements/agent-260724-automatic-session-default-projects.md)

## Context

Azents currently has two root AgentSession creation contracts. Explicit non-primary Session creation receives `existing_project_paths` and ordered setup actions from the caller. Automatic creation paths, currently External Channel binding creation and team-primary ensure, create a root SessionAgentContext without Projects because they have no workspace-selection input.

The existing `agent_project_defaults` records the last non-empty workspace selection used by explicit non-primary Session creation. It is replaced as an incidental side effect of later Session creation, can contain existing-Project and Git-worktree items, and is projected to the Web draft composer as `last_created_session`. The confirmed requirements instead introduce stable administrator-managed existing-Project defaults for root Sessions created without explicit workspace intent.

Subagent Sessions are not independent workspace initialization boundaries. A child SessionAgent and its hidden AgentSession reuse the parent root's SessionAgentContext and Project registry.

## Decision Backlog

1. Choose the durable source of truth for administrator-managed Agent default Projects.
2. Define the root Session creation boundary that applies explicit workspace intent or Agent defaults atomically.
3. Define validation and failure behavior when a configured Project is no longer an eligible existing Project at automatic Session creation time.
4. Define management projection, authorization, and update concurrency for the Agent defaults.

## Decisions

### agent-260724/ADR-D1. Store automatic root Session defaults separately from last-created-Session defaults

**Affects:** `agent-260724/REQ-1`, `agent-260724/REQ-3`, `agent-260724/REQ-4`, `agent-260724/REQ-7`

Introduce a separate administrator-managed Agent configuration as the durable source of truth for existing Projects applied to automatic root Sessions. Keep `agent_project_defaults` as the independent last-created-Session workspace selection used by the Web draft experience.

The automatic-session configuration supports only the existing-Project scope confirmed by this snapshot. Explicit Session creation and its recency-default side effects do not read, merge, or mutate the administrator policy.

**Rejected:** Reusing `agent_project_defaults` would let ordinary explicit Session creation silently change the automatic-Session policy and would admit worktree items outside this snapshot. Replacing the current recency behavior with one administrator default would change the existing Web new-Session experience beyond the confirmed requirements.

### agent-260724/ADR-D2. Use one explicit root Session workspace initialization contract

**Affects:** `agent-260724/REQ-2`, `agent-260724/REQ-3`, `agent-260724/REQ-4`, `agent-260724/REQ-5`, `agent-260724/REQ-6`

Introduce one root Session creation service whose caller supplies an explicit workspace intent: caller-supplied existing Projects or the Agent's automatic-session defaults. The service creates the AgentSession, root SessionAgentContext, and initial context Projects atomically. An explicit empty Project list remains an intentional empty workspace and never falls back to Agent defaults.

External Channel creation, team-primary ensure, and future automatic root producers use the Agent-default intent. Existing Web/Public API non-primary creation uses the explicit intent. Subagent creation remains a separate parent-context inheritance path and does not call root workspace initialization.

**Rejected:** Integrating the policy independently into each automatic producer would duplicate lookup, transaction, and future-adoption rules. Repository inference from omitted values, `start_reason`, or `primary_kind` would create hidden fallback behavior and could not represent explicit empty selection safely.

### agent-260724/ADR-D3. Validate defaults when saved and snapshot them without Runtime I/O at Session creation

**Affects:** `agent-260724/REQ-1`, `agent-260724/REQ-2`, `agent-260724/REQ-5`, `agent-260724/REQ-7`

Validate that configured paths are eligible existing Projects when an administrator saves the Agent policy. Automatic root Session creation then snapshots the stored paths exactly and does not call the Runtime or silently filter entries. Later filesystem drift is represented through normal Project status and runtime operation errors without blocking Session identity, External Channel binding creation, or team-primary ensure.

Changing the configuration requires the Runtime validation path to be available. A temporarily unavailable Runtime prevents that management write but does not prevent automatic Session creation from an already persisted policy.

**Rejected:** Revalidating every path before every automatic Session would couple identity and routing creation to Runtime availability. Silently omitting unavailable Projects would produce a Session context different from the administrator's configured snapshot.

### agent-260724/ADR-D4. Store normalized Agent Workspace paths as configured Project identity

**Affects:** `agent-260724/REQ-1`, `agent-260724/REQ-2`, `agent-260724/REQ-4`, `agent-260724/REQ-7`

Store each configured default Project as a normalized absolute path under the Agent Workspace root. Each automatic root Session snapshots those paths into new context-local Project rows.

A filesystem move requires an explicit administrator update to the Agent policy. Session Project IDs remain local to one root SessionAgentContext, and `agent_project_catalog` remains a status/read projection rather than configuration ownership authority.

**Rejected:** Catalog row IDs would couple durable policy to projection lifecycle and freshness. Existing Session Project IDs cannot be reused across independent root contexts.

### agent-260724/ADR-D5. Replace the complete policy with an optimistic revision precondition

**Affects:** `agent-260724/REQ-1`, `agent-260724/REQ-4`

Expose the Agent's configured default Projects as one ordered policy snapshot. A management write validates the complete submitted path list and atomically replaces the policy only when the caller's expected revision matches the current revision. An empty list clears the policy. A stale revision returns a conflict and does not apply a partial update.

Only Agent administrators may read or replace this management policy. Applying the policy to automatic root Sessions is read-only and never advances its revision.

**Rejected:** Per-item mutations would create partial configuration states and a larger validation/concurrency surface. Last-write-wins complete replacement would let concurrent administrators silently overwrite each other.

## Decision Summary

The accepted decisions separate administrator policy from Web recency defaults, centralize explicit root workspace initialization, validate policy writes rather than automatic Session creation, store normalized paths, and replace the policy atomically with optimistic concurrency. No additional requester-level ADR decisions remain before the complete Design and feasibility validation.
