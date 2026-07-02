---
title: "Claude Rules Loader Implementation Plan"
created: 2026-07-02
tags: [backend, engine, runtime, toolkit, plan]
---
# Claude Rules Loader Implementation Plan

## Source of Truth

- Design: `docs/azents/design/claude-rules-loader.md`
- ADR: `docs/azents/adr/0088-claude-rules-loader.md`
- Existing spec: `docs/azents/spec/domain/toolkit.md`
- Current AGENTS.md loader: `python/apps/azents/src/azents/engine/tools/builtin_agents.py`
- Runtime toolkit resolution: `python/apps/azents/src/azents/engine/run/resolve.py`
- Runtime hook dispatcher: `python/apps/azents/src/azents/engine/hooks/dispatcher.py`

## Stack Shape

```text
origin/main
← feature/claude-rules-loader
← feature/claude-rules-loader-plan
← feature/claude-rules-loader-runtime-context
← feature/claude-rules-loader-toolkit
← feature/claude-rules-loader-validation
← feature/claude-rules-loader-spec
← feature/claude-rules-loader-cleanup
```

## Phase 1 — Design and ADR

- Branch: `feature/claude-rules-loader`
- Scope:
  - Add the collaborative design document.
  - Add ADR-0088 for the long-term runtime instruction-loading policy.
  - Regenerate `docs/azents/INDEX.md`.
- No runtime behavior changes.
- Verification:
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
  - pre-commit documentation hooks.
- Provides for next phase:
  - Accepted decisions and boundaries.

## Phase 2 — Multi-phase Implementation Plan

- Branch: `feature/claude-rules-loader-plan`
- Scope:
  - Add this implementation plan.
  - Define PR boundaries, validation matrix, and spec impact candidates.
- No runtime behavior changes.
- Verification:
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
  - pre-commit documentation hooks.
- Provides for next phase:
  - Reviewable implementation stack boundaries.

## Phase 3 — Shared Runtime Instruction Context

- Branch: `feature/claude-rules-loader-runtime-context`
- Purpose:
  - Extract runtime file-instruction context currently implicit in `RuntimeToolkit` so multiple auto-bound runtime instruction Toolkits can share it.
- Boundary:
  - Do not implement Claude rules discovery yet.
  - Preserve existing AGENTS.md behavior exactly.
  - Do not change model-visible tool schemas.
- Expected changes:
  - Introduce a small shared context object for Runtime FileStorage and sorted registered Projects.
  - Ensure the context is prepared only when runtime tools are enabled and runtime file tools are exposed.
  - Update AGENTS.md appendix code to consume the shared context without changing appendix text or dedupe semantics.
  - Keep Runtime unavailable behavior unchanged for existing read/file tools.
- Verification scope:
  - Existing `RuntimeToolkit` and AGENTS.md appendix tests continue to pass.
  - Add regression tests proving AGENTS.md appendices still appear for successful `read` and still dedupe by path.
  - Add tests proving runtime-independent builtin tools remain available when runtime tools are disabled.
- Provides for next phase:
  - Stable context-sharing boundary for `ClaudeRulesToolkit`.

## Phase 4 — ClaudeRulesToolkit Implementation

- Branch: `feature/claude-rules-loader-toolkit`
- Purpose:
  - Implement the separate auto-bound `ClaudeRulesToolkit` and rule discovery/matching logic.
- Boundary:
  - Append only after successful `read` results.
  - Do not support `.opencode/rules`.
  - Do not support nested `.claude/rules` below arbitrary subdirectories.
  - Do not change AGENTS.md renderer output.
- Expected changes:
  - Add `ClaudeRulesToolkit` with slug `claude_rules`.
  - Auto-bind it whenever runtime tools are enabled.
  - Register `on_after_tool_call` and `on_session_compact` hooks.
  - Add Toolkit State model for path-based dedupe under namespace/state dedicated to Claude rules.
  - Discover rules under `/workspace/agent/.claude/rules/**/*.md` and `<project.path>/.claude/rules/**/*.md`.
  - Apply workspace-root rules before Project-root rules.
  - Keep first root-order occurrence when realpath dedupe finds duplicates.
  - Parse optional `paths` frontmatter; accept string or list of strings.
  - Match globs with the repo-local Codex hook semantics, including path-segment-aware `**`.
  - Render raw rule file content, including frontmatter, in a `<system-reminder>` appendix.
  - Use a Claude-rules-specific per-file cap and truncation marker.
  - Skip repo/config-level issues quietly.
  - Log Runtime/FileStorage communication failures after successful reads and return unchanged output.
  - Let Toolkit State failures and code bugs raise to the dispatcher.
- Verification scope:
  - Unit tests for rule discovery roots, deterministic traversal, realpath dedupe, and symlink policy.
  - Unit tests for `paths` parsing and malformed/unsupported frontmatter quiet skips.
  - Unit tests for glob matching, including relative root-scoped globs, absolute globs, and `**` behavior.
  - Unit tests for raw rendering and truncation.
  - Hook/toolkit tests for successful read append, failed read unchanged, non-read unchanged, dedupe, compaction reset, and failure handling.
  - Resolution tests for auto-binding when runtime tools are enabled and no auto-binding when disabled.
- Provides for next phase:
  - Implemented runtime behavior ready for integration validation.

## Phase 5 — Validation and Integration Evidence

- Branch: `feature/claude-rules-loader-validation`
- Purpose:
  - Run planned validation against the implemented behavior and fix discovered integration issues.
- Boundary:
  - Prefer focused fixes for implementation defects found during validation.
  - Do not promote specs in this phase unless a spec change is needed to unblock validation.
- Validation matrix:

| Scenario | Expected behavior | Evidence |
| --- | --- | --- |
| No `.claude/rules` directory | Successful read unchanged, no log noise | Unit/integration test |
| Workspace global rule | Rule raw content appended once after read | Hook/toolkit test |
| Project global rule | Project rule appended for Project file | Hook/toolkit test |
| Workspace + Project global | Both append in workspace then Project order | Hook/toolkit test |
| `paths` relative glob match | Matching rule appended | Unit + hook test |
| `paths` relative glob non-match | Rule not appended | Unit + hook test |
| Absolute glob | Normalized absolute match works | Unit test |
| Malformed frontmatter | Rule skipped quietly | Unit test with log assertion if practical |
| Symlink inside root | Rule can load and dedupes by realpath | Unit test |
| Symlink outside root | Rule skipped quietly | Unit test |
| Repeated reads | Previously appended rule path not repeated | Hook/toolkit test |
| Compaction | Dedupe clears and rule can append again | Hook/toolkit or dispatcher test |
| Runtime/FileStorage communication failure after read | Error log, unchanged output | Hook/toolkit test |
| Toolkit State failure | Exception reaches dispatcher fail-open path | Hook + dispatcher test |

- Commands:
  - `cd python/apps/azents && uv run pytest src/azents/engine/tools/builtin_test.py`
  - `cd python/apps/azents && uv run pytest src/azents/engine/hooks/dispatcher_test.py`
  - Add and run targeted tests for the new Claude rules module.
  - `cd python/apps/azents && uv run ruff check --fix . && uv run ruff format . && uv run pyright`
- Fixture/prerequisite support:
  - No external credentials required.
  - Use fake/in-memory FileStorage and Toolkit State stores for unit tests.
  - If integration runtime evidence is added, use local runtime file storage fixtures with a registered Project row.
- Provides for next phase:
  - Validation evidence and any bug fixes needed before spec promotion.

## Phase 6 — Spec Promotion

- Branch: `feature/claude-rules-loader-spec`
- Purpose:
  - Promote implemented behavior into current specs after validation.
- Scope:
  - Update `docs/azents/spec/domain/toolkit.md`.
  - Add code paths for the new Claude rules module and resolution changes as needed.
  - Mark `docs/azents/design/claude-rules-loader.md` as implemented with the implementation completion date.
  - Keep ADR-0088 immutable after adoption; do not edit it for implementation details unless the decision itself changed before adoption.
  - Run `/spec-review` or equivalent manual review before finalizing the PR.
- Verification:
  - Documentation index/frontmatter validation.
  - Targeted tests from implementation phases if spec edits accompany fixes.
- Provides for next phase:
  - Current living spec aligned with shipped behavior.

## Phase 7 — Cleanup

- Branch: `feature/claude-rules-loader-cleanup`
- Purpose:
  - Remove temporary implementation planning artifacts after implementation and spec promotion are complete.
- Scope:
  - Remove this plan if the feature is fully shipped and current specs/ADR/design are sufficient.
  - Remove stale phase-specific plan documents if any were added.
  - Do not change runtime behavior.
- Verification:
  - Documentation index/frontmatter validation.

## Dependencies

- Phase 3 depends on Phase 2.
- Phase 4 depends on the shared context boundary from Phase 3.
- Phase 5 depends on Phase 4 implementation.
- Phase 6 depends on Phase 5 validation evidence.
- Phase 7 depends on Phase 6 spec promotion.

## Spec Impact Candidates

- `docs/azents/spec/domain/toolkit.md`
  - Runtime hook provider contract remains unchanged.
  - Add Claude rules instruction loading behavior beside AGENTS.md loading.
  - Update activation conditions by toolkit if auto-bound `claude_rules` is listed there.
- `docs/azents/spec/flow/agent-execution-loop.md`
  - Only update if implementation changes hook dispatch or tool output pipeline semantics beyond adding the new provider.

## Rollout Notes

- No database migration is expected.
- Existing sessions without `.claude/rules` should see no behavior change.
- Existing sessions with `.claude/rules` will start receiving matching rules after successful reads once the feature is deployed.
- Because the feature is always enabled when runtime tools are enabled, rollback is a code rollback rather than a feature flag toggle in the initial version.

## Known Blockers

None.
