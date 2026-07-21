---
title: "Sandbox Control Phase 1 — AgentRuntime Manager Refactor"
tags: [backend, engine]
created: 2026-05-06
updated: 2026-05-06
implemented: 2026-05-06
document_role: supporting
document_type: supporting-phase
migration_source: "docs/azents/design/in-sandbox-sandbox-client-control-channel-phase1-runtime-manager.md"
---

# Sandbox Control Phase 1 — AgentRuntime Manager Refactor

## Goal

Before implementing control channel, change the authoritative sandbox manager API to be centered on `AgentRuntime.id`. Keep the existing session-bound API only as wrappers for migrating later call sites.

## Changes

- Add `SessionSandboxManager.get_or_allocate_runtime()`.
- Add `get_runtime_file_storage()`, `get_runtime_pod_ip()`, `get_runtime()`, `invalidate_runtime()`, `delete_runtime()`, and `release_runtime()`.
- Existing session-bound APIs such as `get_or_allocate()`, `get_file_storage()`, and `delete()` resolve session → runtime and then delegate to runtime-centric methods.
- Correct `session_sandbox.py` and manager module docstring around AgentRuntime ownership.

## Intentionally Not Doing

- Do not rename classes/files. Handle this in separate cleanup after all call sites are migrated.
- Do not migrate every shell/workspace browser call site in one PR.
- Handle gRPC protocol and registry implementation in later phase.

## Verification

- sandbox manager unit/integration tests
- existing tests related to shell/workspace browser
- nointern ruff/pyright/pytest
