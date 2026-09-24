---
title: "Brave Search Phase 2 Management UI Execution Plan"
created: 2026-09-25
tags: [agent, toolkit, search, implementation]
---

# Brave Search Phase 2 Management UI Execution Plan

## Phase Execution Plan

- Phase: `2/3 — Toolkit management UI`
- Branch/base: `feature/brave-search-2-management-ui` → `feature/brave-search-1-backend` (PR #1932).
- PR boundary: Workspace and Agent-owned Brave Toolkit create/edit forms with a masked, replaceable API key, bounded search settings, and an explicit quota-bearing connection test.
- Inputs: confirmed [brave-260925/REQ](../requirements/brave-260925-native-search-toolkit.md), accepted [brave-260925/ADR-D1](../adr/brave-260925-native-search-toolkit.md), approved [brave-260925/DESIGN](../design/brave-260925-native-search-toolkit.md) revision `1`, and phase-1 backend provider/configuration contract.
- Deliverables: M1 and M3 user-facing management surface, credential edit/redaction, optional settings and opt-in Web connection test through existing Toolkit mutation; reuse Agent and workspace Toolkit form paths.
- Non-goals: Brave MCP UI, new credential authority, live paid test in required CI, new API route/client, original-image download, E2E fixtures or publication automation.
- Interfaces: `brave_search` type, `api_key` secret, `country` (including omitted `ALL` sentinel), `search_lang`, `safesearch`, and `timeout`; existing tRPC Toolkit testConnection accepts handle/optional agentId, config, credentials and optional toolkitConfigId.
- Approved Design mechanisms: `M1`, `M3` (M2 and M4–M6 remain fixed by approved Design and phase 1).
- Authority references: `brave-260925/REQ-1`, `REQ-2`, `REQ-6`; Toolkit, Agent, and credential/redaction Living Specs; `brave-260925/ADR-D1`.
- Design delta: `None`
- Removal obligations: `None` in this phase; phase 1 owns the only required removal.
- Absence verification: no new frontend secret storage, alternate Brave endpoint/runtime or implicit paid search; no API schema drift.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Toolkit form integration | `/root` | `typescript/apps/azents-web/src/features/toolkits/containers/useToolkitFormContainer.ts`, `components/ToolkitForm.tsx`, nearby tests | phase-1 config and existing form paths | create/edit defaults and Brave field routing | focused unit/component tests, typecheck |
| Brave field UI and localization | `/root` | `typescript/apps/azents-web/src/features/toolkits/components/BraveSearchConfigFields.tsx`, colocated tests/stories, `typescript/apps/azents-web/messages/**` | Toolkit credentials redaction conventions | safe API key edit, search settings and explicit connection test | focused tests, lint, format, typecheck |
| Independent review | `/root/brave-reviewer` | read-only integrated phase diff | root validation | security/interface/authority findings | written review |

- Integration order: create field component and localization → wire into shared and Agent Toolkit form → exercise credential save/edit and connection tests → integrated frontend checks → single reviewer → corrections → commit and PR.
- Independent review: `/root/brave-reviewer` reviews the stable integrated diff against the approved Requirements/ADR/Design and this phase plan, requested only after root validation.
- Final validation: root-owned focused frontend tests, format/lint/typecheck, OpenAPI unchanged check, documentation snapshot validation and `git diff --check`; browser E2E belongs to phase 3.
- Scope-drift check: retain existing Toolkit scopes/management paths and masked credentials, do not introduce a Brave MCP, automatic search during form render, stored client-side key, or channel-specific behavior.
- Context checkpoint: phase-1 PR #1932 open with 136 focused tests; phase 2 adds UI only. Phase 3 remains deterministic testenv/QA/spec promotion and temporary plan cleanup.
