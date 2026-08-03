---
title: Derive Agent Workspace paths only from current Runner-reported Runtime evidence — never from fixed absolute paths, server HOME, or Provider mount configuration.
---

# Use Runner-Reported Agent Workspace Paths

The Runner is the filesystem authority for its effective Agent Workspace.

- ALWAYS pass the current validated `AgentRuntime.workspace_path` explicitly into Agent Workspace path boundaries, prompts, and discovery logic.
- NEVER add a fixed absolute Agent Workspace root or a historical-path fallback.
- NEVER treat server `HOME` or Provider mount configuration as Runtime workspace evidence.
- Provider deployment code may configure a concrete mount and align Runner `HOME` and working directory with it. Tests and historical documentation may use concrete paths as fixtures or history.

## Bad

```python
AGENT_WORKSPACE_ROOT = "/workspace/agent"
root = runtime.workspace_path or AGENT_WORKSPACE_ROOT
```

## Good

```python
root = normalize_agent_workspace_root(runtime.workspace_path)
normalized = normalize_session_workspace_path(path, workspace_root=root.as_posix())
```
