---
title: "Codex-first Subagent Prerequisites Implementation Plan"
created: 2026-07-08
updated: 2026-07-08
tags: [backend, engine, toolkit, documentation]
---
# Codex-first Subagent Prerequisites Implementation Plan

## Summary

This plan ships the prerequisite work needed before implementing the new subagent model. It is intentionally independent from model-visible subagent behavior. No subagent collaboration tools, child `SessionAgent` creation surface, or Subagent Tree UI are exposed by this stack.

The goal is to remove adjacent architectural drift first so the later subagent implementation stack can focus on subagent-specific behavior.

## Design Link

- [Codex-first Subagent Redesign Implementation Design](codex-first-subagent-redesign.md)
- [ADR-0096: Codex-first Subagent Redesign](../adr/0096-codex-first-subagent-redesign.md)

## Stack Prefix

`subagent-prereq`

## PR Stack

### PR 1 — Design and prerequisite implementation plan

Scope:

- Add ADR-0096.
- Add the overall implementation design.
- Add this prerequisite implementation plan.
- Add the subagent implementation plan when available so reviewers can see the split.

Validation:

- `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`

### PR 2 — Session input producer and wake boundary cleanup

Scope:

- Keep `input_buffers` as internal pending model-input storage.
- Add or clarify a low-level input-buffer writer that only appends rows and returns created rows.
- Split fixed-semantics producers for user messages, turn actions, system reminders, and a future agent mailbox seam.
- Remove generic caller-provided wake ownership from the low-level writer path.
- Preserve current behavior for first messages, direct session messages, edited messages, slash/operation TurnActions, goal/system continuations, live pending input, and broker wake-ups.

Validation:

- Focused backend tests for input buffer, chat write, agent session input, TurnAction/action execution, and goal/system reminder paths.
- Ruff/Pyright for touched backend modules.

### PR 3 — Toolkit taxonomy and execution-mode filter groundwork

Scope:

- Split current memory auto-bound behavior into Memory Read and Memory Write capabilities at toolkit-resolution granularity.
- Keep root-session behavior equivalent.
- Add execution-mode filtering seam for future subagent mode without registering subagent tools.
- Keep Memory Read eligible for future subagent mode when memory is enabled.
- Keep Memory Write excluded from future subagent-mode auto-binding.
- Keep Goal Toolkit root/user-facing and excluded from future subagent-mode auto-binding.
- Rename or prepare runtime toolkit taxonomy around `runtime` instead of `shell` where this can be done without breaking public current behavior unexpectedly.

Validation:

- Toolkit resolution unit tests.
- Root session tool catalog snapshot/update tests.
- Memory Read/Write and Goal exclusion tests at the resolver/filter seam.
- Regenerate clients if public API or schemas change.

### PR 4 — Head-bound context fork helper and FilePart placeholders

Scope:

- Add reusable `fork_turns` parser/validator for `"none"`, `"all"`, and positive integer strings.
- Add reusable fork range selection from the current model-input head/compaction boundary.
- Ensure positive integer values select latest N turns only inside the current model-visible range.
- Add FilePart placeholder rendering for forked transcript context.
- Do not copy object storage blobs, create child ModelFiles, or share ModelFile rows.
- Keep the helper unexposed to model-visible tools in this stack.

Validation:

- Unit tests for parser valid/invalid values.
- Unit tests for model-input head boundary behavior.
- Unit tests for FilePart placeholder content and no blob/ModelFile copy path.

### PR 5 — Root SessionAgentContext Project/worktree foundation

Scope:

- Add root `SessionAgent` and `SessionAgentContext` creation for normal root sessions.
- Add `agent_sessions.session_kind`, defaulting normal sessions to `root`.
- Move active Project registry ownership to `session_agent_context_projects`.
- Move Azents-owned Git worktree allocation/cleanup authority to `session_agent_context_git_worktrees`.
- Preserve existing root-session Project selection, Project browser, runtime Project prompt, and `create_git_worktree` behavior.
- Keep Agent Project catalog/defaults/presets Agent-owned.
- Do not expose child `SessionAgent` creation or collaboration tools.

Validation:

- Migration/repository tests for root `SessionAgent`, context, projects, and worktrees.
- Existing session creation tests.
- Existing Project registration/removal/browser tests.
- Existing worktree creation/cleanup tests.
- Runtime Project prompt loading tests.
- OpenAPI/client regeneration if public route shapes change.

### PR 6 — Prerequisite validation, ADR/requirements mapping, and gap closure

Scope:

- Inspect actual code from PRs 2-5 against ADR-0096 and this plan.
- Produce an ADR/requirements-to-code mapping table in the PR body or a validation report document.
- Start from the assumption that gaps may exist until verified against code.
- Fix all discovered prerequisite-stack gaps in this PR or by amending/rebasing the responsible earlier PR.
- Run final prerequisite-stack quality checks.

Required mapping columns:

| Source | Requirement | Expected code path(s) | Observed implementation | Status | Gap/fix PR |
| --- | --- | --- | --- | --- | --- |

Completion rule:

- This prerequisite ship-feature is not complete until every required row is `Implemented` or explicitly `Deferred` with a reason that is outside the prerequisite scope.

## Dependencies

- PRs are stacked in order.
- CI monitoring starts only after all planned prerequisite PRs are opened.
- Subagent implementation stack must not start from an unverified prerequisite base unless explicitly accepted.

## Spec Impact Candidates

Spec promotion is not the primary output of the prerequisite stack unless current behavior changes become externally visible. Likely affected specs once the prerequisite stack is complete:

- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/domain/toolkit.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/file-exchange-storage.md`

If prerequisite phases change current root-session behavior or public API, update the related living spec in the same PR. Otherwise, defer full subagent spec promotion to the subagent implementation stack.

## E2E and Fixture Requirements

This stack should not expose new user-facing subagent behavior. E2E coverage is regression-focused:

- Create a normal session with selected Projects.
- Create a session with a `create_git_worktree` setup action.
- Send/edit user messages and verify wake/live behavior.
- Verify existing runtime Project prompt behavior through backend tests or diagnostic testenv support.

No subagent fixture is required in this stack.

## Rollout

No feature flag. Intermediate code remains unexposed by not registering child subagent creation surfaces, model-visible collaboration tools, or Subagent Tree UI.

## Cleanup

Temporary validation reports may be removed after the final subagent stack completes and living specs are current. This implementation plan should be removed in the final cleanup stack unless it remains useful historical rationale.
