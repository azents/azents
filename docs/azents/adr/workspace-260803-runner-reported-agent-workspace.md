---
title: "Runner-Reported Agent Workspace"
created: 2026-08-03
tags: [runtime, workspace, runner, provider, architecture]
document_role: primary
document_type: adr
snapshot_id: workspace-260803
---

# Runner-Reported Agent Workspace

- Snapshot: `workspace-260803`
- Document reference: `workspace-260803/ADR`
- Requirements: [Runner-Reported Agent Workspace Requirements](../requirements/workspace-260803-runner-reported-agent-workspace.md) (`workspace-260803/REQ`)

## Context

The Runtime protocol already carries Agent Workspace path evidence from both
Provider reports and Runner registration/state reports. The server currently
stores Provider evidence, requires Runner evidence to match it, and retains
multiple hardcoded consumers of one historical path. That makes infrastructure
configuration an application-level path authority and prevents otherwise valid
Runner environments from selecting another home directory.

## Decisions

### workspace-260803/ADR-D1: Make current Runner evidence authoritative

**Affected requirements:** `workspace-260803/REQ-1`, `REQ-2`, `REQ-5`

The current-generation Runner registration and state report own Agent Workspace
path authority. Runtime Control validates the Runner-reported value and stores it
in `agent_runtimes.workspace_path`. Provider lifecycle reports no longer contain,
validate, or clear Agent Workspace path metadata.

Provider infrastructure retains authority over durable volume lifecycle and where
that volume is mounted into its workload. Configuring the Runner process to use the
mount does not make Provider observation a second metadata authority.

**Rejected alternatives:**

- Provider authority with Runner equality validation was rejected because the
  Runner is the component that executes filesystem operations and knows its
  effective process home.
- Accepting either Provider or Runner evidence was rejected because it creates two
  competing sources of truth and ambiguous failure recovery.

### workspace-260803/ADR-D2: Resolve explicit Runner input before HOME

**Affected requirements:** `workspace-260803/REQ-3`

The Runner accepts an explicit workspace path startup argument. When omitted, it
reads `HOME`. It normalizes and requires an absolute non-empty path before creating
the workspace or connecting to Runtime Control.

Providers set `HOME` and the process working directory to their configured mount
path. They do not inject a separate Provider-authoritative metadata value.

**Rejected alternatives:**

- A Runner-specific required environment variable was rejected because it
  duplicates the standard process home contract.
- An image-defined product workspace constant was rejected because image build
  layout must not decide Runtime metadata.

### workspace-260803/ADR-D3: Pass the reported root through every path boundary

**Affected requirements:** `workspace-260803/REQ-4`, `REQ-5`, `REQ-6`

Server services and Runtime Toolkits receive the normalized current Agent Workspace
root explicitly. Project paths, generated worktree paths, Agent-level Skill and
instruction roots, and durable file-publication paths derive from it. Static tool
schemas avoid concrete home paths; dynamic Runtime guidance may render the actual
reported path.

Stored absolute paths that are no longer descendants of the current root are
invalid. Azents does not translate them to a new root or retain a historical
fallback.

**Rejected alternatives:**

- Reading a server process `HOME` was rejected because server and Runner
  filesystems are unrelated.
- Keeping a shared server constant only for validation was rejected because it
  would continue to reject valid Runtime-specific paths.
- Rewriting persisted paths across roots was rejected because path identity and
  filesystem contents cannot be inferred safely.

## Consequences

- Runner readiness now supplies the Agent Workspace path needed by workspace
  features.
- A running Provider without a connected valid Runner has no usable Agent
  Workspace metadata.
- Existing deployments can retain their configured mount path while alternative
  paths become first-class.
- Provider protocol and tests lose obsolete workspace metadata fields and mismatch
  failure modes.
