---
title: "Claude Rules Loader Validation Report"
created: 2026-07-02
tags: [backend, engine, runtime, toolkit, validation]
---
# Claude Rules Loader Validation Report

## Scope

This report validates the Phase 4 Claude rules loader implementation before living spec promotion.

Validated implementation branch:

- PR: https://github.com/azents/azents/pull/138
- Head branch: `feature/claude-rules-loader-toolkit`
- Head commit validated locally: `0b77678e4f2028fe557f92312aea69474daddb97`

## Environment

- Local repository: `/workspace/agent/azents-claude-rules-loader`
- Subproject: `python/apps/azents`
- Python environment: project `uv` virtual environment
- CI workflow: GitHub Actions `CI` on PR #138

## Commands and Results

Local validation:

| Command | Result |
| --- | --- |
| `cd python/apps/azents && uv run pytest src/azents/engine/tools/claude_rules_test.py -q` | `16 passed, 3 warnings` |
| `cd python/apps/azents && uv run ruff check src/azents/engine/tools/claude_rules_test.py && uv run ruff format --check src/azents/engine/tools/claude_rules_test.py` | Passed; file already formatted |
| `cd python/apps/azents && uv run pytest -q` | `1009 passed, 289 skipped, 5 warnings` |

Commit hooks during validation fixes also ran and passed:

- merge conflict checks
- whitespace and EOF checks
- Ruff check and format
- OpenAPI dump
- Pyright for `python/apps/azents`

CI validation on PR #138:

| Check group | Result |
| --- | --- |
| `changes` | Passed |
| `ci-pre-commit` | Passed |
| `ci-python-run (python/apps/azents)` | Passed |
| Python library/runtime-provider jobs | Passed |
| `ci-python-e2e-run` and `ci-python-e2e` | Passed |
| Docker build matrix | Passed |
| TypeScript and Helm aggregate checks | Passed or skipped as expected by change detection |

## Validation Matrix

| Scenario | Expected behavior | Evidence | Result |
| --- | --- | --- | --- |
| No `.claude/rules` directory | Successful read is unchanged and emits no rule appendix | `TestClaudeRulesToolkit` no-match behavior through fake storage with empty/missing rules | Passed |
| Workspace global rule | Raw rule content is appended once after a successful read | `test_successful_read_appends_workspace_and_project_rules_once` | Passed |
| Project global rule | Project rule is appended for a Project file | `test_successful_read_appends_workspace_and_project_rules_once` | Passed |
| Workspace plus Project global rules | Rules append in workspace-root then Project-root order | `test_successful_read_appends_workspace_and_project_rules_once` | Passed |
| Relative `paths` glob match | Matching rule appends for the target path | `TestRuleMatchesTarget` glob cases | Passed |
| Relative `paths` glob non-match | Non-matching rule is skipped | `TestRuleMatchesTarget` glob cases | Passed |
| Absolute glob | Normalized absolute match works | `TestRuleMatchesTarget` absolute glob case | Passed |
| Malformed frontmatter | Rule is skipped quietly | `TestRuleMatchesTarget` malformed metadata case | Passed |
| Symlink inside root | First realpath occurrence is kept | `test_realpath_dedupe_keeps_first_root_order_occurrence` | Passed |
| Symlink outside root | Rule is skipped quietly | `test_symlink_outside_owner_root_is_skipped` | Passed |
| Repeated reads | Previously appended rule paths are not repeated | `test_successful_read_appends_workspace_and_project_rules_once` | Passed |
| Compaction | Dedupe clears and a rule can append again | `test_compaction_clears_dedupe` | Passed |
| Runtime/FileStorage communication failure after read | Error is logged and output remains unchanged | `test_runtime_storage_failure_logs_and_keeps_output_unchanged` | Passed after CI-only assertion fix |
| Toolkit State failure | Exceptions remain owned by the hook dispatcher fail-open path | Existing hook dispatcher exception tests and Claude rules hook code path review | Passed |

## Failures Found and Fixes Applied

### CI-only log capture assertion failure

Initial CI for PR #138 failed in `TestClaudeRulesToolkit.test_runtime_storage_failure_logs_and_keeps_output_unchanged` because the test asserted against `caplog.text`, which was empty in the GitHub Actions full-suite run despite local passing behavior.

Fixes applied to PR #138:

1. Narrowed log capture to the `azents.engine.tools.claude_rules` logger.
2. Replaced the log text assertion with a direct `logger.exception` call assertion via `monkeypatch` and `Mock` so the test validates the implementation's logging call without depending on global log capture state.

After the second fix, the local full backend suite and PR #138 CI passed.

## Implementation vs. ADR-0088 Comparison

| ADR-0088 decision | Implementation status | Evidence |
| --- | --- | --- |
| Adopt Claude rules loading as a separate auto-bound runtime Toolkit with slug `claude_rules` | Implemented | `ClaudeRulesToolkit`, `ClaudeRulesToolkitProvider`, and runtime auto-binding tests |
| Resolve the Toolkit whenever runtime tools are enabled | Implemented | Runtime resolve, executor, and subagent plumbing tests |
| Expose no model-visible tools and no Toolkit/system prompt content | Implemented | `update_context()` returns no tools; provider has empty prompt |
| Register `on_after_tool_call` and `on_session_compact` hooks | Implemented | Toolkit hook tests for read append and compaction reset |
| Use shared runtime file context instead of `RuntimeToolkit` internals | Implemented | `RuntimeInstructionContextStore` shared between runtime and Claude rules Toolkits |
| Append only to successful `read` tool results and preserve original read failures | Implemented | Hook tests for successful reads, failed reads, and non-read tools |
| Do not touch Runtime solely to discover rules during prompt construction | Implemented | Discovery occurs only from the after-read hook using existing runtime context |
| Store only dedupe metadata in Toolkit State; runtime filesystem remains canonical | Implemented | `ClaudeRulesAppendixDedupeState` stores appended paths only; rule content is read from `FileStorage` |
| Support workspace and registered Project `.claude/rules/**/*.md` roots only | Implemented | Root selection and discovery tests |
| Keep nested `.claude/rules` roots and `.opencode/rules` out of scope | Implemented | Discovery is limited to workspace and Project rule roots |
| Support global rules and `paths` globs with relative, absolute, and `**` semantics | Implemented | `rule_matches_target` unit tests |
| Render raw rule content with a Claude-rules-specific cap | Implemented | Rendering and truncation tests |
| Dedupe by normalized rule path and clear on compaction | Implemented | Hook dedupe and compaction tests |
| Render workspace rules before Project rules and keep first realpath occurrence | Implemented | Hook ordering and realpath dedupe tests |
| Skip repo/config-level issues quietly | Implemented | Discovery and matching tests for missing, malformed, unsupported, missing race, decode, and outside-root cases |
| Log Runtime/FileStorage communication failures after a successful read and return unchanged output | Implemented | Failure-handling test; PR #138 CI passed after log assertion stabilization |
| Let Toolkit State failures and code bugs raise to the hook dispatcher fail-open path | Implemented | Code path review and existing dispatcher exception tests |
| Follow-up work: implement Toolkit, add helper/hook tests, update living spec after implementation | Completed in stack | PR #138 implements/tests, PR #140 promotes `docs/azents/spec/domain/toolkit.md` |

No ADR-0088 decision drift was found.

## Implementation vs. Design Comparison

| Design requirement | Implementation status | Evidence |
| --- | --- | --- |
| Separate auto-bound runtime Toolkit with slug `claude_rules` | Implemented | `ClaudeRulesToolkit`, `ClaudeRulesToolkitProvider`, runtime resolution tests |
| Append only after successful `read` results | Implemented | Hook tests for successful read, failed read, and non-read |
| Use runtime filesystem as source of truth | Implemented | Discovery reads from `FileStorage` during hook execution |
| Support workspace and registered Project `.claude/rules/**/*.md` roots | Implemented | Root selection and discovery tests |
| Apply workspace rules before Project rules | Implemented | Hook appendix ordering test |
| Path-based dedupe reset on compaction | Implemented | Dedupe and compaction tests |
| Parse optional `paths` frontmatter with string/list values | Implemented | Rule matching tests |
| Skip malformed frontmatter and repo/config issues quietly | Implemented | Rule matching and discovery tests |
| Log runtime communication failure and preserve original output | Implemented | Failure handling test and CI evidence |
| Keep AGENTS.md renderer output unchanged | Preserved | Existing backend suite and CI passed |

## Spec Drift Review

Current spec drift is expected until Phase 6 spec promotion.

| Spec | Current state | Required Phase 6 update |
| --- | --- | --- |
| `docs/azents/spec/domain/toolkit.md` | Describes AGENTS.md read-result appendix behavior but not Claude rules loading | Add Claude rules instruction loading behavior, code paths, activation conditions, matching rules, dedupe, and failure behavior |
| `docs/azents/spec/flow/agent-execution-loop.md` | Hook dispatch semantics remain unchanged | No update needed unless spec review identifies a missing hook-output replacement detail |

## Conclusion

The Phase 4 implementation is validated. The remaining planned work is living spec promotion followed by cleanup of temporary implementation planning artifacts.
