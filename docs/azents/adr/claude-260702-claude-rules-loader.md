---
title: "Adopt Claude Rules Loader as a Separate Runtime Toolkit"
created: 2026-07-02
tags: [backend, engine, runtime, toolkit, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: claude-260702
historical_reconstruction: true
migration_source: "docs/azents/adr/0088-claude-rules-loader.md"
---
# claude-260702/ADR: Adopt Claude Rules Loader as a Separate Runtime Toolkit

## Context

Azents already supports repository instructions through `AGENTS.md` read-result appendices. [deterministic-260628/ADR](./deterministic-260628-deterministic-catalog-and-mcp-snapshots.md) decided that `AGENTS.md` should not be injected through Toolkit prompt fragments. Instead, applicable instruction files are appended to successful `read` results, deduped by path in session Toolkit State, and reloaded from the runtime filesystem when needed.

Many repositories also use Claude Code style `.claude/rules/**/*.md` files for modular coding rules. These rules may include YAML frontmatter with `paths` globs. Repo-local Codex/OpenCode hooks can emulate this behavior outside Azents, but Azents itself needs product-runtime support so agents receive the same repository rules when working through Azents runtime file tools.

The key design tension is whether Claude rules should behave like Claude Code's prompt-level active rules or like Azents' existing AGENTS.md runtime instruction model. Prompt-level injection would make rules feel more always-on, but it would reintroduce mutable filesystem content into stable prompt construction and conflict with the current prompt-cache and runtime-touch policy.

## Decision

Adopt Claude rules loading as a separate auto-bound runtime Toolkit.

- The Toolkit slug is `claude_rules`.
- It is resolved whenever runtime tools are enabled.
- It exposes no model-visible tools and no Toolkit/system prompt content.
- It registers runtime hooks for:
  - `on_after_tool_call`: append applicable rules after successful `read` results.
  - `on_session_compact`: clear path-based dedupe state.
- It uses shared runtime file context instead of directly depending on `RuntimeToolkit` internals.

Claude rules follow the AGENTS.md instruction-loading boundary:

- Append only to successful `read` tool results.
- Do not inject rules into the system prompt, Toolkit prompt, or turn-start prompt.
- Do not start or touch Runtime solely to discover rules during prompt construction.
- Store only dedupe metadata in Toolkit State; the runtime filesystem remains canonical.

Supported rule roots in the initial version:

1. `/workspace/agent/.claude/rules/**/*.md`
2. `<registered Project root>/.claude/rules/**/*.md`

Nested `.claude/rules` roots and `.opencode/rules` are out of scope.

Rules without `paths` are global for their source root. Rules with `paths` use the same glob semantics as the repo-local Codex Claude-rules hook:

- Relative globs resolve against the source owner root.
- Absolute globs match normalized absolute runtime paths.
- `**` matches zero or more path segments.

Rendering and state policy:

- Append raw rule file content, including frontmatter.
- Use a Claude-rules-specific per-file content cap.
- Dedupe by normalized rule path, not content hash.
- Clear dedupe on session compaction.
- Workspace rules render before Project rules; Project file reads can receive both.
- Duplicate resolved real paths keep the first root-order occurrence.

Failure policy:

- Repo/config-level issues are skipped quietly with no appendix warning and no server log: missing rules directory, malformed frontmatter, unsupported `paths`, invalid glob, outside-root symlink, non-file entry, individual file race/missing, and individual decode failure.
- Original `read` tool failures are preserved; the Claude rules loader appends nothing.
- Runtime/FileStorage communication failures after a successful read are logged as errors and return unchanged output.
- Toolkit State update failures and code bugs raise and are handled by the runtime hook dispatcher fail-open path.

Symlink policy:

- Symlinks under `.claude/rules` may be followed.
- The resolved real path must stay inside the source owner root.
- External shared-rule symlinks are skipped quietly in the initial product runtime feature.

## Consequences

Positive:

- Azents supports common Claude Code rule files without changing prompt construction policy.
- Rule loading stays consistent with AGENTS.md: filesystem-canonical, read-result appendix, path dedupe.
- Separate Toolkit ownership keeps hook ordering explicit and avoids folding more responsibilities into `RuntimeToolkit`.
- Repo configuration mistakes do not generate server log noise or interrupt user work.
- Infrastructure failures remain observable through logs or hook failure telemetry.

Negative:

- Rules are not visible before a file is read. A direct `write`/`edit` without a prior `read` will not get Claude rules first.
- Content changes to an already-appended rule path are not re-appended until compaction/reset or explicit rule-file read.
- External symlinked shared rules are not supported initially, even though Claude Code can use that pattern.
- `.opencode/rules` users need a future compatibility feature.

## Alternatives Considered

### Prompt-level active rules

Rejected. It is closer to Claude Code behavior, but conflicts with [deterministic-260628/ADR](./deterministic-260628-deterministic-catalog-and-mcp-snapshots.md)'s prompt stability and runtime-touch decisions.

### Add Claude rules to RuntimeToolkit as another mixin

Rejected. It would be easier to implement, but the accepted direction is a separate Toolkit so hook provider order controls append order naturally.

### Support `.opencode/rules`

Rejected for the initial implementation. The adopted feature is Claude rules support. Additional rule roots should be explicit compatibility additions.

### Nested rule roots

Rejected for the initial implementation. Azents will follow the filesystem Skill source-root model: workspace root and registered Project root only.

### Log malformed repo rules

Rejected. Malformed rule files are repository configuration issues and should not create server log noise.

## Follow-up Work

- Implement `ClaudeRulesToolkit` and a shared runtime instruction context.
- Add helper tests for rule discovery, glob matching, symlink handling, truncation, and raw rendering.
- Add hook/toolkit tests for successful read append, failed read unchanged, dedupe, compaction reset, and failure handling.
- Update `docs/azents/spec/domain/toolkit.md` after implementation to describe current behavior.

## Migration provenance

- Historical source filename: `0088-claude-rules-loader.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
