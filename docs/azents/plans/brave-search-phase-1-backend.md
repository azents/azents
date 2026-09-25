---
title: "Brave Search Phase 1 Backend Execution Plan"
created: 2026-09-25
tags: [agent, toolkit, search, implementation]
---

# Brave Search Phase 1 Backend Execution Plan

## Phase Execution Plan

- Phase: `1/3 — backend and file admission`
- Branch/base: `feature/brave-search-1-backend` → `origin/main`
- PR boundary: API-configurable native Brave Toolkit with five tools, bounded proxy-thumbnail outputs, ordered multi-image client result admission, and focused backend evidence; frontend presentation form and full E2E follow later.
- Inputs: confirmed [brave-260925/REQ](../requirements/brave-260925-native-search-toolkit.md), accepted [brave-260925/ADR-D1](../adr/brave-260925-native-search-toolkit.md), approved [brave-260925/DESIGN](../design/brave-260925-native-search-toolkit.md) revision `1`.
- Deliverables: M1–M5 backend portion: encrypted credential-backed provider registration and connection test, direct Brave client for web/context/news/images/videos, one-call multiple model/participant image outputs.
- Non-goals: browser form, full E2E/testenv fixture, channel publication changes, paid live calls, managed Runtime, Brave MCP service, original-image fetching.
- Interfaces: `ToolkitType.BRAVE_SEARCH` and provider registry; typed config/credential models; five static FunctionTools; `FunctionToolResult.generated_files` carrying ranked images; one client call with distinct `(call_id, output_index)`; existing Exchange/ModelFile and Tool Search contracts unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5` (`M6` unchanged in this phase).
- Authority references: `brave-260925/REQ-1` through `REQ-6`, `brave-260925/ADR-D1`, Toolkit, Conversation, file-exchange, and agent execution Living Specs.
- Design delta: `None`
- Removal obligations: replace one-image client generated-file admission and call-ID-only duplicate restriction in `engine/events/provider_output.py`; do not change provider-hosted generation validation.
- Absence verification: ranked two-image client-result test succeeds; duplicate output index rejects before upload; existing provider duplicate-call identity test remains green; grep/behavior checks preserve independent search and channels.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Multi-image client output | `/root` | `python/apps/azents/src/azents/engine/events/provider_output.py`, focused tests | Existing output/file lifecycle | stable rank order, duplicate guard, atomic cleanup | focused pytest, provider regression |
| Brave direct provider and client | `/root` | `python/apps/azents/src/azents/engine/tools/brave_search*.py`, `core/tools.py`, `engine/tools/deps.py`, relevant tests | approved ADR and model/file interface | five typed bounded operations, fixed-host thumbnail fetch, secret-safe failures | focused pytest, Ruff, ty |
| Backend management contract | `/root` | `services/toolkit/**`, `api/public/toolkit/**` only if needed | provider/credentials | owned config validation and test connection | focused service/API tests, OpenAPI diff |
| Independent review | `/root/brave-reviewer` | read-only full integrated phase diff | stable implementation and root validation | authority/security/file lifecycle/interface review | written findings |

- Integration order: multi-image admission and regression → direct API typed client and fetch validation → provider functions and registry → credential/connection tests → integrated Python checks → review → corrections → commit and phase PR.
- Independent review: `/root/brave-reviewer` reviews the frozen root-integrated phase diff against the exact approved Design mechanisms, accepted ADR and Requirements; primary agent requests once stable and reruns affected checks after fixes.
- Final validation: targeted pytest for generated outputs, provider mapping, security and credential boundaries; `uv run ruff check`, `uv run ruff format --check`, configured type check; docs snapshot validation and `git diff --check`. E2E belongs to phase 3, not silently counted as passed here.
- Scope-drift check: all M1–M5 backend behavior present and no new unapproved mode, credential source, persistent state, automatic channel publish, arbitrary URL fetching, or modified provider-image identity policy.
- Context checkpoint: branch begins at `2f9062c81` with untracked approved Requirements/ADR/Design files. Later phases depend on final backend schemas and the first open PR.
