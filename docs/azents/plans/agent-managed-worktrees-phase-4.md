---
title: "Agent-Managed Dynamic Worktrees Phase 4 Execution Plan"
created: 2026-08-12
tags: [agent, external-channel, e2e, runtime, git, worktree, spec]
---

# Agent-Managed Dynamic Worktrees Phase 4 Execution Plan

## Phase Execution Plan

- Phase: `4 — Validation, Living Specs, and cleanup`
- Branch/base: `feature/agent-worktrees-4-validation` → `feature/agent-worktrees-3-remove`
- PR boundary: deterministic lifecycle and External Channel continuity evidence, Living Spec promotion, implementation snapshot completion, and temporary plan cleanup without product-code changes
- Inputs: completed Phase 3 branch-preserving removal at `9c942a38b`; confirmed `worktree-260812/REQ`; accepted `worktree-260812/ADR`; approved `worktree-260812/DESIGN` revision 2; open stacked PRs `#1268`, `#1270`, and `#1271`
- Deliverables: deterministic Agent-managed create, fresh-Run target Skill load, dirty refusal, forced and clean removal, branch preservation, Slack Binding continuity and final publication, proxy request evidence, promoted Living Specs, matching implementation dates, and final stacked PR/CI verification
- Non-goals: new product behavior, compatibility fallbacks, direct database fixture writes, live provider credentials, branch deletion, changes to archive/manual cleanup semantics, PR merge, or live infrastructure mutation
- Interfaces: existing public Chat, Agent automatic-session Project, External Channel connection/Binding, model/provider, Dynamic Worktree Toolkit, Runtime Runner Git, Project projection, Skill projection, and Slack delivery boundaries
- Approved Design mechanisms: `M1` through `M11`
- Authority references: `worktree-260812/REQ-1` through `REQ-7`; `worktree-260812/ADR-D1` through `ADR-D3`; `worktree-260812/DESIGN` revision 2; current Conversation, Toolkit, Workspace, Agent Execution Loop, and Run Resume Specs
- Design delta: `None`
- Removal obligations: remove the implementation plan and all phase plans after their material behavior is promoted into current Living Specs; retain generated branches after Agent removal; retain no proxy assertion that contradicts the terminal model-request lifecycle
- Absence verification: final tree has no `agent-managed-worktrees-*.md` plan files; Agent removal E2E proves checkout/Project absence with branch presence; static diff contains no product-code change or branch-deletion call

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Deterministic model evidence | `/root` | `testenv/azents/e2e/src/support/image_generation_openai_proxy.py`, proxy unit tests | Phase 1 bridge and Phase 2/3 tools | exact initial/continuation/Skill/publication stage evidence | proxy unit tests, Ruff, formatter, `ty` |
| Lifecycle E2E | `/root` | `test_session_git_worktree_lifecycle.py` | complete create/remove lifecycle | create, fresh Run, Skill load, dirty refusal, force removal, Project cleanup, branch preservation | focused and full lifecycle pytest |
| External Channel continuity E2E | `/root` | `test_external_channels.py` | public Slack connection, automatic Project policy, Runtime fixture | same Binding survives create/fresh Run and receives final publication; clean removal preserves branch | focused Slack/worktree pytest and provider evidence |
| Living Spec promotion | `/root` | affected `docs/azents/spec/**`, Requirements and Design snapshot headers | validated feature behavior | current behavior in Living Specs and matching `implemented` dates | spec review and documentation hooks |
| Independent review and stack completion | `hardtack` | read-only stable Phase 4 diff | completed validation and docs | authority, security/data-loss, E2E trustworthiness, scope, and cleanup review | findings resolved, PR created, all stack CI checked |

- Integration order: proxy unit evidence → lifecycle E2E → Slack Binding continuity E2E → Living Spec and snapshot audit → plan cleanup → complete static and E2E validation → independent review → commits and stacked PR creation → CI monitoring
- Independent review: `hardtack` reviews the stable Phase 4 diff read-only against Requirements, ADR, approved Design revision 2 M1–M11, promoted Specs, and this plan; findings are limited to authority/spec drift, security or data loss, false-positive E2E evidence, missing lifecycle/Binding continuity, removal-obligation failure, or material scope drift
- Final validation: E2E Ruff and formatter; E2E `ty --error-on-warning`; proxy unit tests; focused lifecycle and Slack continuity E2E; full lifecycle E2E file; `git diff --check`; spec review; repository pre-commit hooks; and required GitHub checks for all four stacked PRs
- Scope-drift check: Phase 4 changes only deterministic fixture/tests and documentation; validated behavior remains exactly the approved create/fresh-Run/remove lifecycle with no new product authority or compatibility behavior
- Context checkpoint: Phase 4 ends after Living Specs own current behavior, temporary plans are absent from the final tree, PR 4 is open on PR 3, and all required stacked CI is green; no PR is merged
