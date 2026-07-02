---
title: "Filesystem Skill Projection Design"
created: 2026-07-02
updated: 2026-07-02
tags: [architecture, backend, engine, toolkit, frontend]
---

# Filesystem Skill Projection Design

## Overview

This design reintroduces Azents Skills as filesystem packages while keeping the session loop independent from live runtime filesystem availability.

The canonical Skill source is a filesystem package with a `SKILL.md` entrypoint. Azents materializes the relevant `SKILL.md` files into deterministic session-scoped Toolkit State projection revisions. The session loop, Skill prompt, `/actions`, `load_skill`, and Skill action handling read from the adopted projection revision, not from the runtime filesystem.

This document is the implementation design for the decisions recorded in [ADR-0087: Filesystem Skill Projection Revisions](../adr/0087-filesystem-skill-projection-revisions.md).

## Goals

- Keep Skill authoring filesystem-native and compatible with existing `SKILL.md` package conventions.
- Avoid runtime filesystem reads on the normal session-loop read path.
- Keep prompt rendering, `/actions`, and `load_skill` consistent for a whole run.
- Preserve legacy nointern Skill prompt behavior with only the required path-based loading changes.
- Support duplicate Skill slugs across registered Projects without hidden precedence.
- Expose Skills as composer actions through the existing `/actions` model.
- Keep parent and subagent Skill projections independent.

## Non-goals

- No DB-canonical Skill authoring model.
- No runtime-read-on-use `load_skill` implementation.
- No periodic, watcher-immediate, or arbitrary stale-while-revalidate Skill sync.
- No `list_skills`, `refresh_skills`, `create_skill`, `update_skill`, `delete_skill`, or `search_skills` model-visible Skill tools in MVP.
- No full package-resource projection in MVP. Only `SKILL.md` frontmatter, metadata, and body are projected.
- No generic action-handler registry in MVP. The action/toolkit abstraction is tracked separately.

## Current Code Baseline

Relevant current code already exists for parts of the integration surface:

- `python/apps/azents/src/azents/engine/events/action_messages.py`
  - defines `CommandAction`, `GoalAction`, reserved `SkillAction`, and `ActionMessagePayload`.
- `python/apps/azents/src/azents/services/input_buffer.py`
  - owns action-message promotion and currently handles `GoalAction` specially.
- `python/apps/azents/src/azents/api/public/chat/v1/__init__.py`
  - exposes `GET /chat/v1/sessions/{session_id}/actions` for composer action definitions.
- `python/apps/azents/src/azents/api/public/chat/v1/data.py`
  - defines `InputActionDefinitionResponse` and `ChatInputWriteRequest`.
- `python/apps/azents/src/azents/engine/tooling/toolkit_state.py`
  - provides session-bound Toolkit State storage.
- `python/apps/azents/src/azents/core/tools.py`
  - defines Toolkit prompt and tool lifecycle boundaries.
- `python/apps/azents/src/azents/engine/tools/deps.py`
  - wires toolkit providers.
- `python/apps/azents/src/azents/engine/events/litellm_responses.py`
  - lowers `system_reminder` events to model-visible user-role reminders.

The existing `SkillAction` uses `skill_id`. The target public payload should carry `skill_path` instead, because the execution key is the exact projected `SKILL.md` path.

## Skill Source Model

Skill discovery uses only explicit Agent Workspace and Project boundaries.

Initial source conventions:

```text
/workspace/agent/.azents/skills/{slug}/SKILL.md
{project.path}/.agents/skills/{slug}/SKILL.md
{project.path}/.claude/skills/{slug}/SKILL.md
```

Source kinds:

| Source kind | Root | Scope |
| --- | --- | --- |
| `agent` | `/workspace/agent/.azents/skills` | Agent-managed Skills available to the session. |
| `project_agents` | `{project.path}/.agents/skills` | Azents Project-local Skills. |
| `project_claude` | `{project.path}/.claude/skills` | Ecosystem-compatible Project-local Skills. |

Rules:

- Do not recursively scan the whole Agent Workspace.
- Project-local discovery is limited to Projects registered on the session.
- Each Skill identity includes its exact `SKILL.md` path.
- Duplicate slugs are allowed and must remain distinct projection items.
- A malformed `SKILL.md` should not prevent other valid Skills from being projected. The projection should keep sync diagnostics outside the model prompt unless needed for debugging.

## Projection State

Skill projection state is stored as session-scoped Toolkit State under a dedicated Skill namespace.

Conceptual identity:

```text
agent_id = current Agent
session_id = current AgentSession
toolkit_namespace = skill
state_name = projection
```

Conceptual payload:

```json
{
  "schema_version": 1,
  "latest": { "revision_id": "...", "projection_hash": "...", "items": [] },
  "active": { "revision_id": "...", "projection_hash": "...", "items": [] }
}
```

`latest` is the newest completed projection snapshot. `active` is the snapshot frozen for the current run/read path.

A projection item should contain:

| Field | Purpose |
| --- | --- |
| `id` | Stable projection-local item ID. |
| `source_kind` | Source kind from the source model. |
| `project_id` | Registered Project ID when Project-scoped. |
| `project_path` | Registered Project path when Project-scoped. |
| `skill_dir_path` | Absolute Skill package directory path. |
| `skill_path` | Absolute `SKILL.md` path; execution lookup key. |
| `slug` | Directory slug. |
| `name` | Frontmatter `name` when present; otherwise slug. |
| `description` | Frontmatter `description`; empty only when the file is invalid and omitted from prompt/actions. |
| `frontmatter` | Parsed frontmatter needed by prompt/UI. |
| `body` | Full `SKILL.md` content, including frontmatter. |
| `content_hash` | Hash of the projected `SKILL.md` content. |
| `source_label` | Compact source label for UI, such as Project basename or `Agent`. |
| `relative_hint` | Short path hint such as `.agents/skills/code-review`. |

The whole `latest` or `active` snapshot is replaced atomically. The session loop must never observe a partially built projection.

## Projection Lifecycle

Projection synchronization and projection adoption are separate.

### Synchronization

Synchronization reads the runtime filesystem and updates `latest` only. It may run only at deterministic runtime-connected boundaries:

1. session initialization;
2. run end;
3. compaction start;
4. Project list change.

If the runtime is unavailable at a synchronization boundary, skip the sync and keep the existing `latest` snapshot.

### Adoption

Adoption copies the completed `latest` snapshot into `active` only at deterministic read boundaries:

1. run start;
2. the next turn start after compaction completes.

A run uses one `active` snapshot for prompt rendering, `/actions` while running, `load_skill`, and Skill action handling. Do not switch `active` mid-run.

### Idle and running reads

- Idle `/actions` reads `latest` so the composer can show the newest completed projection.
- Running `/actions` reads `active` so selectable actions match the running session-loop read model.
- The model prompt and `load_skill` always read `active`.

### Project source invalidation

Project deletion is a source-set change that can be applied without runtime filesystem access. Creating or refreshing Skill content still requires runtime-connected scanning, but removing a registered Project source does not: the Project registry deletion itself is enough information to remove all projection items that came from that Project.

When a registered Project is removed from a session, Skill projection must remove items with the matching `project_id` or `project_path` from `latest` without reading the runtime filesystem.

`active` handling depends on session run state:

- if the session is idle, remove the Project's items from both `latest` and `active`;
- if a run is in progress, remove the Project's items from `latest` only and keep `active` frozen until the next adoption boundary.

This keeps idle composer actions immediately consistent with the session's registered Project set while preserving the invariant that an in-progress run does not switch active Skill projection mid-run.

## Scanner Behavior

The scanner is not part of the model-visible `SkillToolkit` read path. It is a synchronization service that can access runtime filesystem operations only at synchronization boundaries.

Scanner steps:

1. Read the session's registered Projects.
2. Build the ordered source root list.
3. Discover direct child directories containing `SKILL.md` under each source root.
4. Read each `SKILL.md`.
5. Parse YAML frontmatter.
6. Keep items with enough metadata for prompt/action rendering.
7. Compute content hashes and a projection hash.
8. Save a complete `latest` snapshot when the hash changed.

Ordering for prompt/action rendering must be stable:

1. source priority;
2. Project path;
3. Skill slug/name;
4. full `skill_path` as final tie-breaker.

## SkillToolkit

Skill support should be implemented as a separate core toolkit, similar in deployment shape to Todo/Goal rather than a user-installed external integration.

Responsibilities:

- load the adopted `active` Skill projection from Toolkit State;
- render the deterministic `## Skills` static prompt section;
- expose `load_skill(skill_path)`;
- provide Skill action definitions for `/actions` through service code shared with the API;
- optionally provide a compaction prompt fragment for active Skill continuity.

Non-responsibilities:

- runtime filesystem scanning;
- Skill file authoring;
- generic file operations;
- Project registration;
- action-handler registry abstraction.

`SkillToolkit.update_context()` returns the `load_skill` tool when the active projection contains at least one valid Skill. `SkillToolkit.get_static_prompt()` renders the Skill index from the same active projection. `SkillToolkit.get_dynamic_prompt()` should normally return an empty string.

### Prompt rendering

Keep the legacy nointern Skill prompt wording as the baseline and add only path-based loading details.

Representative output:

```text
## Skills

The following skills are available.
When a task matches a skill, use `load_skill` to load it BEFORE responding.
When the user types `/{skill-name}`, treat it as a request to load and follow that skill.
If a skill's description says 'proactively', use it without waiting for the user to ask.

- **code-review**: Review PRs using Azents conventions.
  Path: `/workspace/agent/azents/.agents/skills/code-review/SKILL.md`
- **code-review**: Review PRs using Menufans conventions.
  Path: `/workspace/agent/menufans/.claude/skills/code-review/SKILL.md`
```

Rules:

- Render only Skill name/slug, description, and exact `skill_path`.
- Do not render full Skill bodies in the prompt.
- Do not render volatile revision IDs or sync timestamps by default.
- If duplicate slugs exist, keep duplicate entries and let the path disambiguate.
- If textual `/code-review` is ambiguous, the model chooses from context or asks for clarification.

### `load_skill(skill_path)`

`load_skill` resolves the exact `skill_path` against the active projection.

Behavior:

- If exactly one item matches, return the full projected `SKILL.md` body and source metadata.
- If no item matches, return a not-found tool error.
- If normalized lookup is ambiguous, return an ambiguity tool error.
- Do not read the runtime filesystem.
- Do not silently fall back to another Skill with the same slug.

Model-visible output should make clear that the Skill was loaded from the active projection, not from a live filesystem read.

## Composer Actions

`GET /chat/v1/sessions/{session_id}/actions` should append Skill actions to the existing command and Goal actions.

Skill action definition mapping:

| Field | Value |
| --- | --- |
| `id` | `skill:{projection_item_id}` or another stable action ID derived from `skill_path`. |
| `keyword` | Skill slug/name, e.g. `code-review`; duplicates allowed. |
| `label` | `/{keyword}`. |
| `description` | Projected Skill description. |
| `action` | `SkillAction(type="skill", skill_path="...")`. |
| `category` | `turn`. |
| `message.policy` | `optional`. |
| `message.placeholder` | `Describe what to do with this skill.` |
| `attachments.policy` | `unsupported` for MVP. |

The UI should render compact source context without making the full path the default label:

```text
/code-review        azents · .agents/skills/code-review
Review PRs using Azents conventions.
```

If the existing generic action response cannot express `source_label` and `relative_hint` cleanly, extend it with optional presentation fields rather than encoding display-only metadata into the execution payload. The execution payload remains the exact `skill_path`.

When a user selects a Skill action, the composer chip can stay compact:

```text
[Skill: code-review]
```

The full path may be available in details, tooltip, accessibility text, or debug UI.

## SkillAction Promotion

MVP handles `SkillAction` in `InputBufferService._promote_action_message_buffer()`, next to the current `GoalAction` branch.

Promotion behavior:

1. Validate and append the durable `action_message` event with the selected `SkillAction` and user-authored message.
2. Resolve `skill_path` against the current active Skill projection.
3. If resolution fails, append a recoverable `system_error` event.
4. If resolution succeeds, append a durable `system_reminder` event that instructs the model to load and follow the selected Skill.
5. Let the normal model-input path lower the `system_reminder` into model-visible input.

The reminder should be compact and path-specific. Representative reminder text:

```text
The user selected the Skill `code-review`.
Load and follow this Skill before responding:
`/workspace/agent/azents/.agents/skills/code-review/SKILL.md`

User request:
{message}
```

The reminder should not inline the full Skill body. The model follows the existing Skill prompt rule and calls `load_skill(skill_path)`, which returns the body from the active projection.

This shape keeps the action durable: if the worker crashes after promotion, the durable `system_reminder` remains actionable model input on retry.

## Compaction Continuity

Skill usage is not persisted as a dedicated current-Skill state field. Compaction should preserve active Skill continuity through the summary prompt.

The compaction prompt should ask the summary model to include active Skill information only when the compacted transcript shows that the Skill still governs unfinished work. Preserve:

- Skill name and `SKILL.md` path if known;
- why the Skill remains active;
- current workflow/checklist stage;
- Skill-specific constraints or output format;
- concrete next actions required by the Skill.

Do not list Skills that were only inspected or used for completed work.

## Subagents

Parent Agents and subagents use independent Skill projections. A subagent does not inherit the parent's active projection implicitly.

If a parent wants a subagent to follow a Skill, the parent must include that instruction in the delegated task. The subagent resolves the Skill from its own active projection and reports a limitation if the Skill is unavailable.

## Implementation Plan

### Prerequisite: restore turn-level dynamic Toolkit context

Before implementing Skill projection, fix the current execution-loop drift where `update_context()`, dynamic Toolkit prompts, and turn-start hooks are effectively collected once per run instead of once per model-call turn.

The prerequisite task should restore the Toolkit State Machine / Runtime Hook contract:

1. collect active toolkit state at each model-call turn boundary;
2. rebuild the tool catalog from that turn's `update_context()` result;
3. collect dynamic prompt fragments for that turn;
4. dispatch `on_turn_start` for that turn's active providers;
5. build the system prompt for the current model call from agent prompt, toolkit prompt fragments, and injected turn prompts;
6. dispatch `on_turn_end` exactly once for started turns.

This is required before Skill implementation because Skill projection adoption after compaction depends on the next model-call turn observing the newly adopted active projection.

### Skill implementation

1. Add Skill projection payload models and store helpers under a Skill-specific module.
2. Add the runtime-connected scanner service and deterministic sync/adoption entry points.
3. Add `SkillToolkit` and wire it as a core toolkit provider.
4. Implement `load_skill(skill_path)` from active projection state.
5. Change `SkillAction` to carry `skill_path` and regenerate public clients.
6. Extend `/actions` to include Skill actions from `latest` or `active` based on session run state.
7. Add Skill action rendering in the web composer slash list and selected chip.
8. Add `SkillAction` handling in `InputBufferService` with durable `system_reminder` promotion.
9. Add compaction prompt guidance for active Skill continuity.
10. Add/update living specs after implementation stabilizes.

## Follow-up Issue

Track the generic action-to-toolkit abstraction in [azents/azents#121](https://github.com/azents/azents/issues/121). MVP intentionally keeps the direct `InputBufferService` branch so the Skill implementation does not introduce a premature action-handler registry.

## Test Strategy

### E2E-primary verification matrix

| Scenario | Expected behavior |
| --- | --- |
| Session with one Project Skill | `/actions` shows the Skill; selecting it produces a Skill action chip; the run loads and follows the Skill. |
| Duplicate Skill slugs in two Projects | `/actions` shows two rows with compact source labels; selected action sends the exact `skill_path`; `load_skill` resolves the selected path only. |
| Runtime unavailable during run start read path | Existing active projection still renders prompt/tools; `load_skill` does not attempt a runtime filesystem read. |
| Skill file edited during a run | Current run keeps using its active projection; changed Skill appears after the next sync/adoption boundary. |
| Skill action worker retry | Durable `action_message` and `system_reminder` allow retry without losing the selected Skill request. |
| Subagent task with parent Skill instruction | Subagent resolves from its own projection and reports unavailable Skill when absent. |
| Compaction during unfinished Skill workflow | Compaction summary preserves active Skill path/stage only when the Skill still constrains pending work. |

### Backend tests

- Projection scanner unit tests for source discovery, frontmatter parsing, malformed files, duplicate slugs, stable ordering, and projection hash changes.
- Toolkit State tests for `latest` replacement, `active` adoption, and no mid-run active mutation.
- `load_skill` tests for exact path match, not found, ambiguity, and no runtime filesystem call.
- `/actions` API tests for idle/latest and running/active selection.
- `InputBufferService` tests for successful Skill action promotion and error promotion.
- Compaction prompt tests for active Skill guidance text.

### Frontend tests

- Slash action list rendering for duplicate Skill rows and compact source labels.
- Selected Skill chip rendering.
- REST payload test that the selected action sends `skill_path`.

### Testenv and fixtures

Use E2E fixtures with temporary Project directories containing `.agents/skills/*/SKILL.md` and `.claude/skills/*/SKILL.md`. Runtime-unavailable behavior can be covered by a fixture or mocked scanner dependency that fails sync while an existing projection remains available.

### Evidence and CI policy

- Run backend unit tests for projection, toolkit, actions, and input-buffer promotion.
- Run frontend tests for slash action UI changes.
- Run the E2E Skill action matrix in CI when the runtime fixture is available.
- If live runtime fixture setup is unavailable, mark only the runtime-dependent E2E cases as skipped with an explicit reason; projection/toolkit/API unit tests must still pass.
