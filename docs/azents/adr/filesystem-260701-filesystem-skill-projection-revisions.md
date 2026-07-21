---
title: "Filesystem Skill Projection Revisions"
created: 2026-07-01
tags: [architecture, backend, engine, toolkit, runtime, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: filesystem-260701
historical_reconstruction: true
migration_source: "docs/azents/adr/0087-filesystem-skill-projection-revisions.md"
---
# filesystem-260701/ADR: Filesystem Skill Projection Revisions

## Context

Azents removed the legacy Skill system before the current Agent Runtime, Agent Workspace, and session-owned Project model stabilized. Skill support is now being reintroduced in a system where three constraints are important at the same time:

1. Skills must be authored and owned as filesystem packages, not as primary DB records.
2. The Agent Runtime is not guaranteed to be running or reachable when a session loop needs to prepare model input.
3. Skill availability is rendered into model-visible prompt/toolkit state, so non-deterministic refreshes can break provider prompt-cache locality.

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-45) reserves the chat input/action-message shape for a future Skill Turn Action:

```json
{
  "action": { "type": "skill", "skill_id": "review-pr" },
  "message": "Review PR #112"
}
```

This ADR records how Skill source, projection, refresh, and runtime/session-loop boundaries should work before implementing the Skill Turn Action and `load_skill` behavior.

## Research notes

### Legacy nointern Skill implementation baseline

The old nointern Skill system was implemented in the builtin shell toolkit and removed by commit `451178990` (`chore(nointern): remove legacy skill 시스템`). The baseline files immediately before removal were:

- `python/apps/nointern/src/nointern/runtime/tools/load_skill.py`
- `python/apps/nointern/src/nointern/runtime/tools/shell.py`
- `python/apps/nointern/src/nointern/runtime/tools/load_skill_test.py`
- `python/apps/nointern/src/nointern/runtime/tools/skill_prompt_test.py`
- `docs/nointern/design/shared-storage-and-skills.md`

The first implementation was added by `149e81f1e` (`shared-storage [5/8]: Phase 3 — 스킬 시스템`) and prompt injection was added by `015361a3d` (`feat(nointern): 스킬 목록 시스템 프롬프트 주입 + 사용 유도`). It loaded `SKILL.md` files from convention-based filesystem locations:

```text
/data/user/skills/{name}/SKILL.md
/data/agent/skills/{name}/SKILL.md
/platform/skills/{name}/SKILL.md
```

The effective precedence was:

```text
user > agent > platform
```

The runtime behavior was:

1. `collect_skill_prompt()` listed skill directories in each scope.
2. It read each `SKILL.md`, parsed YAML frontmatter with `python-frontmatter`, and required `name` and `description` metadata.
3. It deduplicated by `name` using the scope precedence above.
4. It appended a `## Skills` prompt section containing only `name` and `description`.
5. The prompt instructed the model to call `load_skill` before responding when a task matched a skill, to treat `/{skill-name}` as a request to load and follow that skill, and to use proactive skills without waiting when the description said so.
6. The only Skill-specific model tool was `load_skill(name)`.
7. `load_skill` searched the same scopes in precedence order and returned `Skill found at: {path}\n\n{SKILL.md content}`.

A later OpenAI SDK migration attempt (`b16141c2e`) changed `load_skill` to read from a per-turn `list[SkillMetadata]` cache instead of reading File API at tool-call time. `SkillMetadata` contained `name`, `description`, `path`, and full `body`. `BuiltinShellToolkit.update_context()` collected metadata once, rendered the prompt from that metadata, and created `load_skill(skills=self._cached_skills)` for the same turn. This is the closest historical precedent for Azents' current projection direction: prompt index and `load_skill` body came from the same materialized Skill list, not from a second live filesystem read.

The useful baseline properties were:

- `SKILL.md` files were the effective source material;
- prompt injection used frontmatter metadata for progressive disclosure;
- `load_skill` was the only Skill-specific tool;
- `load_skill` returned the full `SKILL.md` body including frontmatter;
- skill authoring was filesystem-based via normal file tools;
- Skills could include filesystem-adjacent resources, scripts, templates, and references.

The main problems were:

- source paths were tied to legacy `/data` storage and EFS/File-API assumptions;
- there was no current Project boundary model;
- global user/agent/platform precedence did not fit session-owned Project registration;
- prompt and tool cache lifecycle was per-turn and did not define deterministic revision/adoption boundaries;
- runtime/filesystem availability and sync semantics were not explicit enough for the current Agent Runtime model.

### Prior redesign discussions

The old menufans/nointern redesign discussions explored Workspace-level Skills, Manifest entries, `SkillScanner`, and sandbox filesystem synchronization. Relevant historical threads included:

- menufans discussion #3011: SDK Workspace usage, Memory/Skills redesign, EFS removal;
- menufans discussion #3027: Workspace-level Skill system;
- menufans discussion #3048: Manifest spec definition;
- menufans issue #3122: Skill / Manifest system redesign;
- menufans issue #3334: Agent skill DB snapshot and sandbox filesystem sync.

The important retained lesson is that scanner-style Skill discovery was not inherently wrong. It was removed because Manifest, Project, authentication, inheritance, and runtime availability policies were not settled. The current Azents model should therefore avoid reintroducing a free-floating Manifest layer before the current Project boundary model requires it.

### Current Azents constraints

Current Azents has:

- Agent-owned long-lived Runtime / Agent Workspace state;
- session-owned Project registrations under the Agent Workspace;
- explicit Project selection at new-session time;
- runtime-gated folder browsing for selecting/registering Projects;
- session-scoped Toolkit State patterns;
- deterministic tool catalog and toolkit prompt rules from [deterministic-260628/ADR](./deterministic-260628-deterministic-catalog-and-mcp-snapshots.md);
- `ActionMessagePayload` and a reserved `SkillAction` variant from [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-46).

The current Project model is path-boundary based. There is no current public Project Source, archive bootstrap, Manifest entry, or Project materialization model. Skill discovery must therefore start from explicit filesystem conventions under the Agent Workspace and registered Project paths.

## Decision

### filesystem-260701/ADR-D1. Use filesystem Skill packages as the canonical source

Skill canonical source is a filesystem package with a `SKILL.md` entrypoint. The DB or Toolkit State must not become the authoring source of truth.

Initial source conventions are:

```text
/workspace/agent/.azents/skills/{slug}/SKILL.md
{project.path}/.agents/skills/{slug}/SKILL.md
{project.path}/.claude/skills/{slug}/SKILL.md
```

The first path is the Agent-managed Skill directory. The Project paths are discovered only from registered Project boundaries for the session. Azents must not recursively scan the whole Agent Workspace as a Skill source.

Future platform/image-bundled Skills may add another source kind, but that is outside this ADR's initial source set.

### filesystem-260701/ADR-D2. Store Skill projections in Toolkit State, not canonical storage

Azents will materialize discovered filesystem Skills into deterministic session-scoped Toolkit State. The projection contains enough data for model prompt/action/load paths to execute without live runtime filesystem access, including the full Skill body.

The projection is not merely a cache with source-read-on-miss behavior. It is the read model used by the session loop. The filesystem remains canonical authoring storage, while Toolkit State is the low-latency projection consumed by toolkit prompt rendering and Skill tools.

A projection item should include at least:

- stable projection-local Skill id;
- source kind;
- source path and Skill directory path;
- optional Project registration id/path;
- slug;
- display name;
- description;
- parsed frontmatter metadata needed by UI and prompt rendering;
- full `SKILL.md` body;
- source content hash;
- projection revision id;
- projection metadata such as indexed time and sync reason.

This ADR intentionally does not introduce a primary `agent_skills` DB model. Durable implementation may use existing Toolkit State persistence, but the domain concept is Toolkit State projection, not DB-canonical Skill storage.

### filesystem-260701/ADR-D3. Keep runtime filesystem reads out of the session-loop read path

The session loop, prompt construction, `load_skill`, and Skill Turn Action handling must read Skills from the active Skill projection revision. They must not wait for runtime filesystem reads.

This applies even though filesystem is canonical. The separation is:

```text
Filesystem Skill package
  -> canonical authoring source

Runtime-connected Skill scanner
  -> source-to-projection synchronization path

Skill projection revision
  -> low-latency session-loop read model
```

If a Skill projection item is missing, the session loop fails fast for that Skill instead of synchronously reading the runtime filesystem. A refresh may be scheduled for the next deterministic synchronization boundary, but it must not block the current model turn.

### filesystem-260701/ADR-D4. Store Skill body in the projection

The Skill body must be materialized into the projection. Prompt rendering can expose only the Skill index, but `load_skill` and Skill Turn Action execution must be able to read the body without runtime access.

For `load_skill`, the model-visible result should identify that the body was loaded from the active projection and may include source metadata such as source path, Project identity, projection revision, and content hash. It should not imply that the filesystem was read at tool-call time.

`load_skill` must require the full `SKILL.md` path. Name-only loading is rejected because registered Projects may contain Skills with the same slug. The path is the projection lookup key, not a request to read the runtime filesystem at tool-call time. This makes Project/source identity explicit and avoids hidden precedence rules for duplicate slugs.

For Skill Turn Actions, the handler should:

1. append/preserve the durable `action_message` event;
2. resolve the Skill from the active projection revision;
3. render a Skill-specific model-visible reminder or enriched input using the projected body;
4. continue normal run-loop behavior.

### filesystem-260701/ADR-D5. Store only `latest` and `active` projection snapshots

Skill projection Toolkit State stores only the snapshots needed for deterministic execution:

```text
latest
active
```

- **latest**: the newest completed projection snapshot for the session/source set.
- **active**: the projection snapshot frozen for the current run/session-loop read path.

Each snapshot still carries a `revision_id`, `projection_hash`, sync metadata, and projected Skill items for debugging and consistency checks, but the MVP does not keep revision history.

Synchronization boundaries update `latest` only. Adoption boundaries copy `latest` into `active`. A run uses one active snapshot for the entire run.

The session loop must not observe a partially built projection. Projection replacement is atomic at the Toolkit State payload level.

### filesystem-260701/ADR-D6. Create new projection revisions only at deterministic runtime-connected boundaries

Azents must not use periodic, watcher-triggered, or arbitrary background Skill synchronization for model-visible Skill state. Non-deterministic refreshes can change the Skill prompt/index unexpectedly and break prompt-cache locality.

New Skill projection revisions are created only at these deterministic read/sync timings, and only when the runtime is connected and filesystem access is available:

1. **Session initialization**
2. **Run end**
3. **Compaction start**
4. **Project list change**

If the runtime is unavailable at one of these boundaries, synchronization is skipped and the existing latest projection remains in place.

These boundaries have the following rationale:

- Session initialization and Project list changes already require runtime-backed folder browsing or Project selection/validation flows, so requiring runtime connectivity is appropriate.
- During a run, if the agent changes Skill files, the agent has performed the file-editing action and can reason about that change without mutating the current run's Skill projection.
- Run-end synchronization prepares the next run without changing the current run's prompt/toolkit state.
- Compaction can remove context and naturally disrupt prompt-cache continuity, so reloading Skill projection at compaction start is an acceptable cache boundary.

### filesystem-260701/ADR-D7. Adopt latest projection revisions only at run/turn boundaries

Creating a latest projection revision and adopting it as the active read model are separate operations.

Azents adopts the latest completed Skill projection revision only at:

1. **Run start**
2. **The next turn start after compaction completes**

This keeps a run's Skill prompt, action list, and `load_skill` behavior stable for the entire run. It also ensures prompt-cache invalidation happens at predictable boundaries.

The common lifecycle is:

```text
Run N start
  -> adopt latest revision rev_10
  -> run uses rev_10

Run N end
  -> if runtime connected, scan filesystem
  -> create rev_11 if changed

Run N+1 start
  -> adopt rev_11
```

For compaction:

```text
Compaction start
  -> if runtime connected, scan filesystem
  -> create latest revision rev_12 if changed

Compaction completes
  -> next turn start adopts rev_12
```

### filesystem-260701/ADR-D8. Do not switch active Skill revision mid-run

Even if a new projection revision is created while a run is active, the active revision for that run does not change.

This avoids these failure modes:

- the system prompt lists one Skill set while `load_skill` reads another;
- provider prompt cache changes in the middle of a logical run;
- Skill action validation differs between input acceptance and processing;
- runtime filesystem availability leaks into the session-loop critical path.

If Project list changes are allowed while a run is active, their new projection revision applies only at the next adoption boundary. The simpler product policy may instead block Project list changes during active runs.

### filesystem-260701/ADR-D9. Keep prompt rendering deterministic and legacy-compatible

Skill prompt/index rendering must be deterministic for a given active projection revision.

Azents should keep the legacy nointern Skill prompt wording as the baseline and adjust only the parts required by current path-based Skill resolution.

Legacy baseline:

```text
## Skills

The following skills are available.
When a task matches a skill, use `load_skill` to load it BEFORE responding.
When the user types `/{skill-name}`, treat it as a request to load and follow that skill.
If a skill's description says 'proactively', use it without waiting for the user to ask.
```

Azents rendering keeps those instructions, but `load_skill` takes `skill_path`, so the rendered index must include the exact `SKILL.md` path for each entry. A representative rendering is:

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

The implementation may include a compact source label or relative path hint when useful, but it should not add large explanatory prose beyond the legacy baseline. The full Skill body is not rendered in the prompt.

The rendering should use stable ordering, for example:

1. source priority;
2. Project path;
3. Skill slug;
4. source path as final tie-breaker.

Prompt text should avoid transient sync state unless it is important for model behavior. Internal revision ids may be useful for debugging, but including volatile revision ids in the system prompt can reduce cache reuse and should be avoided unless needed.

The prompt must not present duplicate slugs as if they were globally unique. When a user writes a textual slash-style request such as `/code-review` without selecting a concrete action entry, the model should choose the most relevant Skill path from the prompt based on the current Project/task context. If the context is insufficient, it should ask for clarification instead of guessing silently.

### filesystem-260701/ADR-D10. Use Project boundaries as the Skill source set

Project-scoped Skill discovery is limited to the session's registered Project paths. This aligns with the current Agent Workspace Project model and avoids reintroducing a Manifest model prematurely.

Nested and overlapping Projects are allowed by the current Project model, so Skill source resolution must handle overlaps deterministically. If two source paths define the same slug, the projection must retain unambiguous Skill identities and may expose deterministic disambiguation in the UI.

Slug collisions must not cause one filesystem Skill to overwrite another projection item silently.

Project deletion is a source-set invalidation that does not require runtime filesystem access. When a registered Project is removed from a session, Azents removes that Project's projection items from `latest` based on `project_id` or `project_path` without scanning the runtime filesystem. If the session is idle, the same invalidation also removes those items from `active`. If a run is in progress, `active` remains frozen until the next adoption boundary.

This separates runtime-connected content refresh from DB-known source-set removal. It keeps idle `/actions` consistent with the registered Project set while preserving the rule that active Skill projection does not switch mid-run.

### filesystem-260701/ADR-D11. Keep Skill editing filesystem-backed

Skill creation and editing UX should write filesystem packages, not primary DB records.

When Azents itself writes a Skill file, it may update or prepare projection data from the known write content, but the resulting projection still represents filesystem source. The new projection should become active only at the normal adoption boundary, not immediately in the middle of an active run.

### filesystem-260701/ADR-D12. Use `/actions` and `SkillAction` for composer integration

Skill actions should be exposed through the session-scoped action listing introduced by [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-47).

`GET /chat/v1/sessions/{session_id}/actions` chooses the Skill projection revision by session run state:

- when the session is idle, it reads the latest completed Skill projection revision;
- when a run is in progress, it reads the active Skill projection revision frozen for that run.

Action processing in the run loop always uses the run's active Skill projection revision.

The action definition should expose slash-search fields from projected metadata and carry the exact `SKILL.md` path for action execution. If two registered Projects both expose `code-review`, the UI can render both as separate actions with distinct Project/source labels while sending the selected action's concrete path.

### filesystem-260701/ADR-D13. Show compact Skill source labels in slash actions

Skill slash actions should separate the user-facing display label from the execution payload.

The execution payload carries the full `SKILL.md` path:

```json
{
  "type": "skill",
  "skill_path": "/workspace/agent/azents/.agents/skills/code-review/SKILL.md"
}
```

The slash list does not need to show the full path by default. It should use:

- `keyword`: Skill slug/name, such as `code-review`; duplicate keywords are allowed.
- primary label: `/{keyword}`.
- source label: compact Project/source label, usually the registered Project folder basename such as `azents` or a reserved label such as `Agent` for Agent-managed Skills.
- secondary path hint: a shortened relative path such as `.agents/skills/code-review` or `.claude/skills/code-review`.
- description: projected Skill description.

Example rows:

```text
/code-review        azents · .agents/skills/code-review
Review PRs using Azents conventions.

/code-review        menufans · .claude/skills/code-review
Review PRs using Menufans conventions.
```

The UI may show the full absolute path only in a tooltip, details popover, accessibility label, or copy/debug affordance. The full path should remain available in the action definition for exact execution even when it is visually shortened.

When source labels collide, the UI should disambiguate progressively instead of showing the full path immediately. For example, two Projects with basename `api` can render parent-qualified labels such as `repo-a/api` and `repo-b/api`. If that is still ambiguous, the UI may fall back to middle-ellipsized absolute paths.

After the user selects a Skill action, the composer chip should emphasize the action kind rather than repeat the Project label. The selected action has already been disambiguated in the slash list, and the payload carries the exact path. A compact chip is enough:

```text
[Skill: code-review]
```

The chip may expose the source label or full path only through hover/details/debug affordances, not in the default compact chip text.

### filesystem-260701/ADR-D14. Keep the Skill toolset minimal: `load_skill` only

The MVP Skill toolkit exposes one model-visible Skill-specific tool:

```text
load_skill(skill_path)
```

`skill_path` is the absolute `SKILL.md` path shown in the active projection's prompt/action list. It identifies both the Skill and its Project/source. Agent-managed Skills use their Agent Skill path under `/workspace/agent/.azents/skills/.../SKILL.md`.

The active projection, not a live filesystem read, resolves `skill_path` to exactly one Skill projection item. If resolution matches no item, the tool fails with a not-found error. If resolution matches multiple items after path normalization, the tool fails with a projection ambiguity error. The tool must not choose silently.

Textual slash-style user input such as `/code-review` is not itself a `load_skill` argument. It is a user request that the model interprets using the rendered Skill index. The model chooses the matching `skill_path` from context, then calls `load_skill(skill_path)`.

The following are not part of the MVP model-visible Skill toolkit:

- `list_skills`
- `refresh_skills`
- `create_skill`
- `update_skill`
- `delete_skill`
- `search_skills`

Skill discovery is provided by the deterministic `## Skills` prompt index and by `/actions`. Skill authoring initially uses normal filesystem tools.

### filesystem-260701/ADR-D15. Implement Skill support as a separate `SkillToolkit`

Azents will implement Skill prompt rendering and `load_skill` as a dedicated `SkillToolkit`, not as additional behavior inside the shell/file toolkit.

The legacy nointern implementation put Skill behavior in `BuiltinShellToolkit` because Shared Storage, file tools, memory, and Skills were all part of the same legacy builtin toolkit. In current Azents, Skill has its own lifecycle constraints:

- it reads from session-scoped Toolkit State projection, not from live runtime filesystem;
- it participates in deterministic projection revision adoption at run/compaction boundaries;
- it contributes a model-visible prompt section;
- it exposes a Skill-specific model tool;
- it backs chat composer Skill actions.

Keeping those responsibilities in a separate toolkit gives a clearer implementation boundary:

```text
SkillToolkit
  -> reads active Skill projection revision from Toolkit State
  -> renders the deterministic ## Skills prompt index
  -> exposes load_skill(skill_path)
  -> provides action-list data for Skill actions
```

Runtime filesystem scanning and projection revision creation should live outside the model-visible `SkillToolkit` execution path. A Skill projection sync service can update Toolkit State at the deterministic sync points defined in this ADR. `SkillToolkit.update_context()` then only reads the active projection revision and returns prompt/tools immediately.

The file/shell toolkit remains responsible for general filesystem tools such as `read`, `write`, `edit`, `grep`, and `glob`. Skill authoring uses those file tools initially, while Skill loading and discovery are handled by `SkillToolkit`.

### filesystem-260701/ADR-D16. Handle SkillAction in `InputBufferService` for MVP

MVP handles Skill Turn Actions by adding a `SkillAction` branch to `InputBufferService._promote_action_message_buffer()`, matching the existing GoalAction pattern.

The branch should keep input-buffer ordering and durable `action_message` preservation in `InputBufferService`, while delegating Skill-specific lookup and model-visible reminder construction to Skill-specific helper/service code where practical.

A generic action-handler registry or action-to-toolkit abstraction is intentionally deferred. The connection between chat actions and toolkit-owned behavior needs a broader abstraction discussion once more Turn Action types exist. Track that as a follow-up issue instead of adding the abstraction in the first Skill implementation.

### filesystem-260701/ADR-D17. Project only `SKILL.md` content in MVP

MVP Skill projection includes only `SKILL.md` frontmatter, metadata, and body. Additional package resources such as `references/`, `scripts/`, `templates/`, and assets remain filesystem resources.

If a Skill body points to additional resources, the agent can read them through normal file tools when runtime filesystem access is available. The projection does not attempt to make the whole Skill package available offline.

This keeps projection size and sync policy small while preserving the filesystem package model.

### filesystem-260701/ADR-D18. Keep parent and subagent Skill projections independent

Parent Agents and subagents each use their own Skill projection. A subagent must not inherit the parent session's active Skill projection implicitly.

Subagent toolkit inheritance semantics need separate design cleanup and should not become a hidden dependency for Skill behavior in this ADR. Skill projection is session-scoped Toolkit State, so each parent or subagent session reads and adopts its own active Skill projection revision.

If a parent wants a subagent to follow a specific Skill, the parent must pass that instruction explicitly in the subagent task. The subagent then resolves and loads a Skill available in its own active projection. If the Skill is not available to the subagent, the subagent should report that limitation rather than silently using the parent projection.

This keeps Skill behavior predictable while leaving broader subagent toolkit/project inheritance for a future revisit.

### filesystem-260701/ADR-D19. Preserve active Skill continuity through compaction prompts, not Skill state

Skill usage is not persistent session state. Azents will not store a dedicated "current Skill" field merely because the model loaded or invoked a Skill.

However, long Skill workflows can lose important procedural context after compaction. To preserve continuity, the compaction summary prompt should ask the summary model to infer whether any Skill is actively governing unfinished work in the compacted transcript.

The compaction prompt should include guidance equivalent to:

```text
If the compacted transcript shows that a Skill is actively being followed for unfinished work,
include an "Active Skill" subsection in the checkpoint. A Skill is active when its instructions,
checklist, workflow stage, or constraints are still needed to continue pending work.

For each active Skill, preserve:
- Skill name and SKILL.md path if known;
- why it is still active;
- the current workflow/checklist stage;
- Skill-specific constraints or output format that the next agent must continue following;
- concrete next actions required by that Skill.

Do not list every loaded Skill. Omit Skills that were only inspected, used for a completed task,
or no longer constrain pending work. If uncertain, mark Needs verification.
```

This keeps the decision with the summary model, which can inspect the transcript for `load_skill` calls, Skill action messages, assistant statements about following a Skill, Todo/Goal state, and unfinished work. The summary should preserve only active Skill handoff information, not turn Skill usage into durable session state.

A generated checkpoint may include this information inside existing sections such as `Current State`, `Pending Work`, or `Notes for Next Agent`, or use a compact subsection such as:

```markdown
### Active Skill
- `code-review` from `/workspace/agent/azents/.agents/skills/code-review/SKILL.md` is still active.
- Current stage: review findings collected; final PR review comment not submitted yet.
- Continue using its output format and severity criteria.
```

SkillToolkit may later provide a compaction prompt fragment or hook registration to keep this instruction colocated with Skill behavior, but the actual active-skill decision remains summary-model inference from transcript evidence.

### filesystem-260701/ADR-D20. Reject DB-canonical Skill storage

Azents rejects a design where Skills are primarily authored and owned as DB rows with optional filesystem materialization.

That design is inappropriate because Skills are packages, not only text snippets. They may have adjacent references, scripts, assets, templates, and Project-local context. Filesystem-first authoring also allows agents and users to edit Skills with normal file workflows and preserves compatibility with ecosystem conventions such as `.claude/skills`.

Azents also rejects adding a dedicated Skill domain table as the primary projection surface for this phase. Skill projection belongs to session-scoped Toolkit State because it is consumed by toolkit prompt/action/tool behavior and must be revisioned with the run's toolkit state.

### filesystem-260701/ADR-D21. Reject runtime-read-on-use Skill loading

Azents rejects a design where `load_skill` or Skill Turn Action handling reads `SKILL.md` directly from the runtime filesystem at use time.

That design makes normal session-loop latency depend on runtime filesystem operations and fails poorly when runtime is stopped or unavailable. It also creates cache instability because Skill prompt/index state and loaded body can diverge within one run.

### filesystem-260701/ADR-D22. Reject periodic or watcher-immediate Skill synchronization

Azents rejects periodic sync, filesystem watcher immediate sync, and arbitrary stale-while-revalidate behavior for model-visible Skill projection.

Even if such refreshes are asynchronous, they can make Skill prompt content change at unpredictable times. Skill projection may be refreshed only at deterministic synchronization boundaries and adopted only at deterministic run/turn boundaries.

## Consequences

- Skill source remains ergonomic and file-native.
- Session loops can run without waiting on runtime filesystem reads.
- Runtime unavailability becomes a synchronization concern instead of a prompt/tool execution concern.
- Skill body storage in projection increases projection size, but it is necessary for low-latency `load_skill` and Skill Turn Action handling.
- Skill changes made during a run apply from the next adoption boundary, not immediately.
- Prompt-cache invalidation becomes predictable: run start and post-compaction turn start are the primary adoption boundaries.
- Compaction can preserve active Skill workflow continuity without introducing a persistent current-Skill state field.
- Parent/subagent Skill behavior remains independent and does not depend on unresolved subagent toolkit inheritance semantics.
- The implementation needs explicit revision bookkeeping and a scanner that can produce complete projection revisions atomically.
- UI may need to distinguish latest known Skills from the active run revision when a run is in progress.

## Open implementation details

The following details are intentionally left to implementation design/spec work:

- exact Toolkit State payload schema;
- exact projection id format and collision policy;
- whether `/actions` should show latest completed revision or active revision while no run is active;
- how much sync metadata should be shown to users;
- whether Project list changes are blocked during active runs or deferred;
- exact model-visible format for Skill invocation reminders;
- whether non-`SKILL.md` resources are indexed in the projection or loaded through normal file tools when needed.

## Migration provenance

- Historical source filename: `0087-filesystem-skill-projection-revisions.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
