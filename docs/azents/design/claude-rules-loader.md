---
title: "Claude Rules Loader Design"
created: 2026-07-02
implemented: 2026-07-02
tags: [backend, engine, runtime, toolkit]
---
# Claude Rules Loader Design

## Problem

Azents already appends applicable `AGENTS.md` files to successful runtime `read` tool results so agents receive path-relevant repository instructions without injecting mutable filesystem state into the stable system prompt. Many repositories also keep Claude Code style rules under `.claude/rules/`. Those rules currently work in Claude Code and repo-local hooks, but Azents does not load them as runtime instructions.

The goal is to support `.claude/rules/**/*.md` in Azents with the same runtime instruction boundary as `AGENTS.md`: load from filesystem only after successful file reads, keep source of truth in the runtime filesystem, avoid prompt-prefix churn, and keep repo configuration issues from disrupting user tasks.

## Goals

- Load applicable Claude Code style rules from `.claude/rules/**/*.md` for files read through the runtime `read` tool.
- Keep the rule source of truth in the runtime filesystem; do not copy rule bodies into durable Toolkit State.
- Preserve the AGENTS.md instruction-loading policy: successful `read` output appendix, not Toolkit/system prompt injection.
- Implement the loader as a separate auto-bound runtime Toolkit so runtime hook provider order naturally controls output order.
- Support path-scoped rules through `paths` frontmatter using the same glob semantics as the repo-local Codex Claude-rules hook.
- Keep repo/config-level rule issues quiet: skip malformed or unsupported rule files without user-facing warnings or server log noise.
- Record system/runtime communication failures as errors instead of silently hiding infrastructure problems.

## Non-goals

- Support `.opencode/rules` in the initial product runtime feature.
- Support nested `.claude/rules` below arbitrary subdirectories inside a project.
- Inject Claude rules into the system prompt, Toolkit prompts, or turn-start user prompts.
- Block `write`/`edit` when a matching rule has not yet been loaded.
- Add user-facing settings or per-agent opt-in/out controls for Claude rules.
- Implement an external repo-local hook mechanism in Azents. The Codex hook remains reference behavior only.

## Current Behavior

Current `AGENTS.md` loading is implemented by `AgentsAppendixMixin` in `python/apps/azents/src/azents/engine/tools/builtin_agents.py` and documented in `docs/azents/spec/domain/toolkit.md`.

Relevant current properties:

- AGENTS.md content is appended only to successful `read` results.
- The loader reads content fresh from Runtime FileStorage while handling the `read` result.
- The loader stores only path-based dedupe state in Toolkit State.
- Compaction clears the dedupe path list so current filesystem content can be appended again later.
- Prompt construction does not start or touch Runtime only to discover instruction files.
- Runtime hook dispatch is fail-open for hook exceptions and records hook failure telemetry.

Current filesystem Skills use a deterministic projection model with source roots for agent and project skill directories. This design follows the same root-scoped source model for Claude rules: workspace root and registered Project roots only.

## Proposed Design

### Auto-bound ClaudeRulesToolkit

Add a separate auto-bound runtime Toolkit, tentatively named `ClaudeRulesToolkit`, with slug `claude_rules`.

Activation:

- The Toolkit is resolved whenever runtime tools are enabled for the session.
- There is no DB ToolkitConfig, user setting, or opt-in/out in the initial version.
- The Toolkit exposes no model-visible tools and no prompt fragments.
- It registers runtime hooks:
  - `on_after_tool_call` to append matching rules after successful `read` results.
  - `on_session_compact` to reset dedupe state.

Ordering:

- Because this is a separate Toolkit, the existing runtime hook provider order determines where its appendix appears relative to AGENTS.md and other output-replacing hook providers.
- The implementation must not special-case AGENTS.md ordering inside the renderer.

### Shared Runtime File Context

`ClaudeRulesToolkit` needs the same runtime context that the AGENTS.md loader currently obtains through `RuntimeToolkit.update_context()`:

- Runtime FileStorage for stat/list/read operations.
- Sorted registered `SessionWorkspaceProject` list.
- Runtime agent/session identity for FileStorage and Toolkit State.

Introduce a small shared runtime instruction context provider so both `RuntimeToolkit`/AGENTS.md loading and `ClaudeRulesToolkit` can use the same FileStorage instance and Project list for a turn. The shared object should be prepared only when runtime tools are enabled and Runtime file tools are being exposed. It must not start or touch Runtime during prompt construction solely to discover rules.

A possible shape:

```python
@dataclass(frozen=True)
class RuntimeInstructionContext:
    file_storage: FileStorage
    projects: tuple[SessionWorkspaceProject, ...]
```

The exact implementation can be adjusted during coding, but the boundary should remain: FileStorage and Project roots are shared explicitly rather than having `ClaudeRulesToolkit` indirectly depend on `RuntimeToolkit` internals.

### Rule Source Roots

For a read target under `/workspace/agent`, candidate rule roots are:

1. Workspace root: `/workspace/agent/.claude/rules/**/*.md`
2. If the target is inside a registered Project: `<project.path>/.claude/rules/**/*.md`

The initial implementation does not walk target ancestors for nested `.claude/rules` roots. This matches the source-root model used by filesystem Skills and avoids scanning arbitrary nested repo configuration.

Ordering and dedupe:

- Evaluate workspace root rules before Project root rules.
- Within each root, traverse deterministically by normalized runtime path.
- If the same resolved real path is discoverable more than once, keep the first occurrence and skip later duplicates.
- If the target is under `/workspace/agent` but outside every registered Project, only workspace root rules apply.
- If the target is inside a registered Project, workspace root rules and Project root rules can both apply.

### Rule File Format

A rule file is any Markdown file under a supported `.claude/rules` root.

Frontmatter:

- Optional YAML frontmatter may contain `paths`.
- `paths` may be a string or a list of strings.
- Unsupported `paths` shapes are treated as repo/config-level issues and the rule file is skipped quietly.
- Malformed frontmatter is treated as a repo/config-level issue and the rule file is skipped quietly.

Rendering:

- Append the raw file content, including frontmatter, rather than stripping frontmatter and rendering only body content.
- Apply a Claude-rules-specific per-file cap, not the AGENTS.md constant. The value can initially match the AGENTS.md cap, but it should have its own named constant.
- If a rule file exceeds the per-file cap, truncate the raw content and append the standard truncation marker for Claude rules. Truncation is normal behavior, not an error.

### Path Matching

Use the same glob semantics as the repo-local Codex Claude-rules hook:

- Relative `paths` globs resolve against the rule root's owner root:
  - `/workspace/agent/.claude/rules/foo.md` resolves relative paths against `/workspace/agent`.
  - `<project.path>/.claude/rules/foo.md` resolves relative paths against `<project.path>`.
- Absolute `paths` globs are matched against normalized absolute runtime paths.
- `**` matches zero or more path segments.
- Matching is path-segment aware and deterministic.

Rules without `paths` are global for their source root:

- Workspace rules without `paths` apply to successful reads under `/workspace/agent/**`.
- Project rules without `paths` apply to successful reads inside that Project.

### Symlink Policy

Rules discovery may follow symlinks under `.claude/rules`, but the resolved real path must stay inside the source owner root:

- Workspace root rule symlinks must resolve inside `/workspace/agent`.
- Project root rule symlinks must resolve inside that Project root.
- Symlinks resolving outside the owner root are skipped quietly.
- Symlink loops must terminate through realpath/visited-set dedupe.

This intentionally does not support external shared-rules symlinks in the initial product runtime feature.

### Dedupe State

Add a new Toolkit State payload for Claude rules, separate from AGENTS.md state.

Suggested identity:

- `toolkit_namespace`: `claude_rules`
- `state_name`: `claude_rules_appendix_dedupe`
- scope: current agent/session, following existing Toolkit State identity conventions.

Suggested payload:

```python
class ClaudeRulesAppendixDedupeState(ToolkitStateModel):
    schema_version: int = 1
    appended_paths: list[str] = Field(default_factory=list)
```

Policy:

- Dedupe is path-based, matching the AGENTS.md policy and filesystem Skill source-root policy.
- Toolkit State stores only normalized paths already provided to the session; it does not store raw rule content, parsed frontmatter, rule body, or file hashes.
- `on_session_compact` clears `appended_paths`.
- If a rule file changes during the same session after it was already appended, it is not appended again until dedupe is reset or the user explicitly reads the rule file itself.

State update failure is a code/system failure. The hook should raise and let the runtime hook dispatcher record the hook failure.

### Appendix Rendering

When matching, not-yet-deduped rules exist, return a `ToolOutputReplace` that appends a separate system reminder block to the current tool output:

```text
<system-reminder>
Relevant Claude rules for the accessed path:

### /workspace/agent/.claude/rules/conventions.md

<raw markdown content>

### /workspace/agent/project/.claude/rules/python.md

<raw markdown content>
</system-reminder>
```

The renderer should not include omitted/malformed warnings. Repo/config-level issues are quiet skips.

### Failure Handling

Failure handling is intentionally split by class.

Repo/config-level issues are skipped quietly with no appendix, no warning log, and no trace event:

- Missing `.claude/rules` directory.
- Malformed frontmatter.
- Unsupported `paths` shape.
- Invalid glob pattern.
- Symlink resolving outside the owner root.
- Non-file entries.
- Individual rule file missing due to race.
- Individual rule file decode failure.

Original `read` tool failures are preserved:

- If the `read` tool itself fails, `ClaudeRulesToolkit` returns unchanged and appends nothing.
- The loader does not add logs or trace for the original read failure.

Runtime/FileStorage communication failures after a successful read are infrastructure failures:

- Log an error from the Claude rules loader.
- Do not append Claude rules for that hook invocation.
- Keep the original successful read output unchanged.
- Do not raise for this class unless the implementation cannot reliably distinguish the communication failure from a code bug.

Code bugs and Toolkit State update failures should raise:

- Let the runtime hook dispatcher record hook failure telemetry and continue fail-open per the Runtime Hook Provider Contract.
- Do not swallow programmer errors in the loader.

### Security and Permissions

- The loader only reads files reachable through Runtime FileStorage under `/workspace/agent` and registered Project roots.
- It does not read local worker filesystem paths directly.
- Symlink targets escaping the source owner root are skipped quietly.
- Raw rule content is inserted only into model-visible tool output appendices, never logs or trace events.
- Hook telemetry must not include raw rule content. If path metadata is included in logs for infrastructure failures, it should be bounded and avoid dumping candidate lists.
- The loader exposes no credentials and no model-visible tools.

### Migration and Rollout

- Add the Toolkit as an auto-bound runtime Toolkit when runtime tools are enabled.
- No database migration is required if Toolkit State can store the new payload dynamically like existing session-scoped state.
- Existing sessions without `.claude/rules` are unaffected.
- Existing AGENTS.md behavior remains unchanged except for hook output order naturally including the new Toolkit provider when it appends rules.
- Update `docs/azents/spec/domain/toolkit.md` after implementation to describe current behavior.

## Alternatives Considered

### Inject rules through system or Toolkit prompt

Rejected. This would better mimic Claude Code's active rule prompt model, but it conflicts with Azents' current AGENTS.md decision to avoid mutable filesystem instructions in prompt-prefix construction.

### Append rules after `write`/`edit`

Rejected for the initial design. The user chose the AGENTS.md policy: successful `read` only. This keeps the loader easy to reason about and avoids post-edit instruction churn.

### Support `.opencode/rules`

Rejected for the initial design. The product feature is Claude rules support. Other agent-specific rule roots can be added later as explicit compatibility features.

### Support nested `.claude/rules` roots

Rejected for the initial design. The user chose the filesystem Skill source-root policy: workspace root and registered Project root only.

### Log malformed repo rules

Rejected. Malformed repo rules are repository configuration issues and would create server log noise. They are skipped quietly.

## Test Strategy

### Unit tests

Add unit tests for the rule discovery and matching helpers:

- Workspace root rule without `paths` applies to any `/workspace/agent/**` read.
- Project root rule without `paths` applies only inside that Project.
- Workspace and Project global rules both apply for a Project file read.
- `paths` string and list frontmatter are accepted.
- Relative globs are resolved against the owner root.
- Absolute globs match normalized absolute runtime paths.
- `**` segment matching follows the Codex hook semantics.
- Malformed frontmatter, unsupported `paths`, invalid glob, non-file entries, decode failures, and outside-root symlinks are skipped quietly.
- Traversal is deterministic and realpath dedupe keeps the first root-order occurrence.
- Raw file content, including frontmatter, is rendered.
- Per-file truncation uses the Claude rules cap and marker.

### Toolkit/hook tests

Add tests around `ClaudeRulesToolkit` behavior:

- Successful `read` with matching not-yet-appended rules returns `ToolOutputReplace` with the appendix.
- Failed `read` returns unchanged.
- Non-`read` tools return unchanged.
- Path-based dedupe prevents repeated append for the same rule path.
- `on_session_compact` clears dedupe state.
- Toolkit State update failure raises and is handled by dispatcher fail-open behavior.
- Runtime/FileStorage communication failure after a successful read logs an error and returns unchanged.

### Resolution/order tests

Add run-resolution tests:

- `ClaudeRulesToolkit` is auto-bound when runtime tools are enabled.
- It is not auto-bound when runtime tools are disabled.
- Hook provider order is deterministic and follows Toolkit binding order.
- The Toolkit exposes no model-visible tools and no prompt fragments.

### E2E/product verification

This feature changes model-visible runtime context rather than UI. Product-level verification can use a lightweight runtime/session E2E or integration test instead of browser E2E:

1. Create a runtime workspace with a registered Project.
2. Add workspace `.claude/rules/global.md` and Project `.claude/rules/project.md`.
3. Run an agent turn that reads a Project file.
4. Verify the read tool result contains both raw rule files in a `<system-reminder>` block.
5. Read another Project file and verify the same rule paths are not appended again.
6. Trigger compaction or directly invoke the compaction hook in an integration test, then verify rules can be appended again.

No live external credentials are required. Fixture setup only needs runtime file storage and a registered Project row.

### Documentation validation

- Update `docs/azents/spec/domain/toolkit.md` with implemented behavior.
- Run the docs index/frontmatter check after adding the design and ADR.
- Run targeted Python tests for the new helper/toolkit modules and existing AGENTS.md appendix tests.
