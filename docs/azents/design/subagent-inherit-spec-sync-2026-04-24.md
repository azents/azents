---
title: "Subagent Inherit Spec Sync Audit Report"
tags: [process, documentation, audit]
created: 2026-04-24
updated: 2026-04-24
implemented: 2026-04-24
document_role: supporting
document_type: supporting-audit
migration_source: "docs/azents/design/subagent-inherit-spec-sync-2026-04-24.md"
---

# Subagent Inherit Spec Sync Audit Report

## 1. Audit Scope

Audit whether Phase A-D changes of Subagent Toolkit/Model Inherit feature (issue #2967) were correctly reflected in nointern Living Spec (`docs/nointern/spec/**`). Manual full audit as extension of `/spec-review`.

### 1.1 Target Spec Files

| Spec | Version | last_verified_at | Main `code_paths` changes |
|---|---|---|---|
| [`spec/domain/agent.md`](../spec/domain/agent.md) | 2 | 2026-04-24 | includes changes to `agent_subagent/data.py`, `agents`, `engine/run/resolve.py`, `engine/tools/subagent.py` |
| [`spec/domain/toolkit.md`](../spec/domain/toolkit.md) | 3 | 2026-04-24 | includes changes to `rdb/models/agent_subagent.py`, `repos/agent_subagent/data.py`, `engine/tools/subagent.py` |
| [`spec/flow/subagent-delegation.md`](../spec/flow/subagent-delegation.md) | 2 | 2026-04-24 | same |

### 1.2 Matching Commits

Full Phase A-D (`plan/subagent-inherit..feat/subagent-inherit/phase-d`) = 14 commits. Spec updates were performed in 4 commits of Phase D (`c9a7cdafa`, `f6efae894`, `b9551fcbf`, `94e1dd4b2`).

### 1.3 Changed Code Files vs `code_paths`

Compare actual file paths changed in Phase A-C with each spec `code_paths` glob pattern.

| Changed file | agent.md | toolkit.md | subagent-delegation.md |
|---|---|---|---|
| `rdb/models/agent.py` | ✅ included (line 26) | — | ✅ included (line 21) |
| `rdb/models/agent_subagent.py` | ✅ (line 29) | ✅ (line 15) | ✅ (line 20) |
| `repos/agent/data.py` | ✅ (`repos/agent/**`) | — | — |
| `repos/agent_subagent/data.py` | ✅ (`repos/agent_subagent/**`) | ✅ (`repos/agent_subagent/**`) | ✅ (`repos/agent_subagent/**`) |
| `services/agent/__init__.py` | ✅ (`services/agent/**`) | — | ✅ (line 18) |
| `services/agent/data.py` | ✅ | — | — |
| `services/agent_subagent/**` | ✅ (→ `repos/agent_subagent/**` — N/A) | ✅ (line 14) | ✅ (line 17) |
| `engine/run/resolve.py` | ✅ (line 24) | — | ✅ (line 15) |
| `engine/run/input.py` | ✅ (line 25) | — | ✅ (line 16) |
| `engine/engine.py` | ✅ (line 34) | — | ✅ (line 11) |
| `engine/tools/subagent.py` | ✅ (`engine/tools/**`) | ✅ (`engine/tools/**`) | ✅ (line 10) |
| `api/public/agent/**` | ✅ | — | — |
| `db-schemas/rdb/migrations/...` | 🟡 migration glob not included (intentional — spec describes final model, not migration) | 🟡 same | 🟡 same |

**Conclusion**: `code_paths` covers **all** changed actual sources. Migration files are intentionally excluded (spec describes current schema and migration history source of truth is `db-schemas/rdb/migrations/`).

## 2. Summary by Category

| Category | Count | Meaning |
|---|---|---|
| **SPEC-UP-TO-DATE** | 10 | spec sections match actual code |
| **SPEC-UPDATE-NEEDED** | 2 | code changed but spec did not keep up (fixed on this branch) |
| **NEW-FLOW-NEEDED** | 0 | no new flow spec needed — included in existing `subagent-delegation.md` as inherit branches §4 / §5.5 |
| **NEW-DOMAIN-NEEDED** | 0 | no new domain spec needed — Agent/Toolkit domain extension is sufficient |
| **ADR-CANDIDATE** | 3 | major design decisions that are candidates for ADR documentation |

## 3. Spec Details

### 3.1 `spec/domain/agent.md` (Agent domain)

#### SPEC-UP-TO-DATE

- §2.2 `llm_provider_integration_id` / `llm_provider_model_id` — changed type `str \| None` and CHECK constraint (`ck_agents_model_not_null_when_role_agent`) both accurately reflected (L116-123).
- §4 Business Rules — newly added `[subagent-model-nullable]`, `[subagent-model-pair]` 2 rules (L449-468). Matches implementation (`services/agent/__init__.py:145-164, 393-412`, `rdb/models/agent.py:170-175`).
- §9 Changelog — `version 2 — 2026-04-24 — added subagent model inherit` entry is correct (L684).
- `last_verified_at: 2026-04-24`, `spec_version: 2` both updated.

#### SPEC-UPDATE-NEEDED

- **S01**: §3.2 Tool Selection Policy L239
  ``Destructive tools such as `shell_recreate_sandbox` are excluded from Subagent (`engine/tools/subagent.py:72` `_EXCLUDED_TOOL_NAMES`)``
  → Code renamed to `MAIN_ONLY_TOOL_NAMES` (`engine/tools/subagent.py:74`).
  **Needs fix (immediately fixed on this branch)**.

#### NEW-FLOW-NEEDED / NEW-DOMAIN-NEEDED

- Not needed. Agent domain internal extension is sufficient.

### 3.2 `spec/domain/toolkit.md` (Toolkit domain)

#### SPEC-UP-TO-DATE

- §"Main-Only Toolkit" — accurately describes two constants: `MAIN_ONLY_TOOL_NAMES` (`shell_recreate_sandbox`) and `MAIN_ONLY_TOOLKIT_TYPES` (currently empty), and why empty (memory/schedule/subagent are blocked by other paths) (L253-290).
- §"Toolkit Inherit (Subagent)" — `agents.toolkit_inherit_mode` column, `'none'` (default) / `'all'` exclusive behavior, inherit target/non-target distinction all accurate (L291-325).
- `code_paths` includes `rdb/models/agent_subagent.py`, `repos/agent_subagent/**`, `services/agent_subagent/**` (Phase D `f6efae894`).
- §Changelog — spec_version 3 entry is correct (L502-507).

#### SPEC-UPDATE-NEEDED

- None. Section was newly written in Phase D and fully consistent with code.

### 3.3 `spec/flow/subagent-delegation.md` (Flow)

#### SPEC-UP-TO-DATE

- Added "Model / Toolkit Inherit (optional)" summary to §1.3 "Core design decisions" (L75-84).
- Reflected pair rule for subagent agent `llm_provider_*_id` in §3 Preconditions (L111-117).
- §4 Sequence expresses model source branch and toolkit source branch as two `alt/else` blocks (L163-176). Matches actual code (`engine/tools/subagent.py:260-272, 318-359`).
- §5.5 "Inherit branch — Model / Toolkit source" table covers all resolve decision points (L276-302).
- §6 Error Cases added 3 cases: `InvalidModelPair` / `ParentModelUnavailable` / main-only filter (L318-321).
- §7 Test Scenarios added 7.7 (toolkit inherit), 7.8 (model inherit), 7.9 (shutdown) (L379-404).
- §10 Changelog — version 2 entry is correct.

#### SPEC-UPDATE-NEEDED

- **S02**: §6 L316 refers to `shell_recreate_sandbox` exclusion mechanism as `_EXCLUDED_TOOL_NAMES`.
  Renamed to `MAIN_ONLY_TOOL_NAMES`. **Needs fix (immediately fixed on this branch)**.

## 4. ADR Candidate Suggestions

These decisions involve trade-offs that may be reverted or extended later, so it is desirable to independently record them as ADR. **Creating ADR files themselves is outside this branch scope** (review in Phase 9 / 10).

### ADR-C1. Junction-level vs Agent-level inherit policy (DP1)

- **Decision**: store in `agents.toolkit_inherit_mode` (agent row). Not an Agent row property.
- **Context**: In M:N structure where same subagent can attach to multiple parents, per-parent policy such as "Parent A inherits, Parent B independent" is needed.
- **Trade-off**: extra attribute on junction vs simplifying as Agent row property and sacrificing reusability. Different form from Claude Agent SDK `model: "inherit"`.
- **Alternative rationale**: DP1 A (agent level) does not fit nointern M:N.
- **Follow-up impact**: Per-toolkit allowlist (`'explicit'`) extension also at same agent row level.

### ADR-C2. Exclusive vs Merge toolkit inherit policy (DP6)

- **Decision**: if `inherit_mode='all'`, use only parent toolkit and **completely ignore** subagent's own `agent_toolkits` in that call. No merge/dedup.
- **Context**: Initial merge design was overturned in review #2976.
- **Trade-off**: simple/clear vs giving up flexibility of "some from parent, some own." No observed need for latter.
- **Follow-up impact**: Settings UI disables subagent toolkit section when "inherit toggle on".

### ADR-C3. NULL = inherit (DP5 A) model inherit schema choice

- **Decision**: make `agents.llm_provider_*_id` nullable; if both are NULL, inherit parent. Not junction flag, not sentinel string.
- **Context**: Initial junction flag design was overturned in review #2976. Semantically isomorphic with Claude Agent SDK `model: "inherit"`.
- **Trade-off**: relax NOT NULL constraint + introduce CHECK constraint vs keep existing NOT NULL + add flag column. NULL is first-class in terms of schema meaning/reference integrity.
- **Follow-up impact**: introduces `resolve_invoke_input_with_model_source` helper and `ParentModelUnavailable` drift-defense Failure.

## 5. Actions

### 5.1 Immediate fixes on this branch

- **SPEC-UPDATE-NEEDED S01/S02**: reflect rename `_EXCLUDED_TOOL_NAMES` → `MAIN_ONLY_TOOL_NAMES` (separate fix commit).
  `spec/domain/agent.md:239`, `spec/flow/subagent-delegation.md:316`.

### 5.2 Carried over follow-ups (Phase 9 Spec Promotion scope)

- Decide whether to create ADR-C1, C2, C3. If created, write in `docs/nointern/adr/NNNN-{slug}.md` format. This audit only **suggests** and actual creation is carried over.
- Move `design/subagent-inherit.md` to `design/subagent-inherit-{YYYY-MM-DD}.md` (`status: archived`, record archive date). Since this branch is right after implementation completion, perform in Phase 9 after ship confirmation.

### 5.3 No carry-over (informational)

- `code_paths` glob patterns intentionally exclude migrations — matches current policy. No change needed.

## 6. Re-audit Loop Result

After one rerun: no additional SPEC-UPDATE-NEEDED. Two cases S01/S02 in §3 are final.

## 7. Conclusion

- All 3 specs **accurately reflect** Phase A-C code changes.
- 2 SPEC-UPDATE-NEEDED cases share same cause (stale `_EXCLUDED_TOOL_NAMES` reference) and are immediately fixed on this branch.
- 3 ADR candidates should be reviewed in Phase 9 (spec promotion).
- `last_verified_at: 2026-04-24` was already updated in Phase D, so drift detection baseline is valid.

## 8. Related Documents

- [Design document](./subagent-inherit.md)
- [Implementation plan](./subagent-inherit-plan.md)
- [Design-implementation audit report](./subagent-inherit-audit-2026-04-24.md)
- Spec: [agent](../spec/domain/agent.md), [toolkit](../spec/domain/toolkit.md), [subagent-delegation](../spec/flow/subagent-delegation.md)
