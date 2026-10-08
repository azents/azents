---
title: "GitHub User Account Toolkit Implementation Plan"
created: 2026-10-08
tags: [github, toolkit, backend, frontend, testenv]
---

# GitHub User Account Toolkit Implementation Plan

- Authority: [Requirements](../requirements/github-261008-user-account-toolkit.md), [ADR](../adr/github-261008-user-account-toolkit.md), [Design](../design/github-261008-user-account-toolkit.md).
- Approved current revision: 4; M1-M10 and M12. M11's cleanup completion/retry lifecycle is retired by the requester's implementation correction.
- Design delta: None relative to revision 4.
- Lead/integration/validation: `/root`; single independent reviewer: `/root/github-user-reviewer`.
- Current integration baseline: main `e9f8ff0276df8e513703bbbba1851f37987edbe4`; preserve removal of obsolete visibility scopes and current shared/Agent ownership.

## Stack

1. Backend authorization/cleanup contracts, `feat/github-user-261008-backend` -> main, [PR #2222](https://github.com/azents/azents/pull/2222). Revise the existing PR to remove superseded cleanup machinery rather than add a separate policy PR.
2. Current UI, `feat/github-user-261008-ui` -> backend. Preserve catalog/details/immediate saves, five modes, Platform availability, popup/review/account sharing confirmation and personal/multi-org readiness. No cleanup pending/retry UI; local disconnection succeeds after the bounded fail-open attempt.
3. Execution/product E2E/Specs, `feat/github-user-261008-execution` -> UI. Current-row MCP and opt-in Runtime, exact-call authentication failure handling, deterministic setup-to-Worker evidence, existing-mode regressions, Spec promotion and plan removal.

Open each predecessor PR before the next implementation phase. Create the complete stack before CI waiting; fix/check every PR. Do not merge, deploy or alter live GitHub registration.

## Ownership and Interfaces

- `/root/github-user-persistence`: user domain DTOs, encrypted active/candidate models, completed repository operations, migration/tests. Return transient affected-token facts instead of persisting cleanup rows.
- `/root/github-user-service`: SDK-backed service/API sequencing and tests. Cleanup expected failures are logged and do not undo/block local effects. No cleanup proof, retry API or completion owner.
- `/root/github-user-provider`: provider SDK adapter and parent deletion integration; no cleanup-based blocker or grant-wide revocation.
- `/root`: remaining UI/tRPC/callback/locales/story/state implementation and all validation, followed by phase-3 execution/product verification after the UI PR. The earlier UI role's partial work is preserved; implementation proceeds directly without waiting on delegated owners.
- `/root`: shared contract integration, generation, all integrated checks/review requests/PRs/CI and final evidence.

All provider I/O remains outside completed repository transactions. Setup and current execution authority stay fail-closed. Token revocation uses the exact captured affected token/App, never a newer connection's token or another authority. A failed attempt can leave the non-expiring token valid at GitHub; local use and state still end.

## Verification and Removal

- Remove cleanup persistence/enum/status/tombstone, retry endpoints/UI, cleanup invalidity probes, parent blockers and owned completion tasks from the unmerged feature. Preserve encrypted active/candidate credentials, one-use/context/current-connection publication, old PAT/installation behavior and normal authentication errors.
- E2E covers representative Platform/BYOA, missing Platform, personal/two-org authority, another participant, staged setup and failure/replacement/disconnection. A synthetic cleanup timeout/rejection must still permit local disconnect/replace/delete.
- Required tests use local synthetic provider/SDK/model/Runtime fixtures. Optional live provider tests remain explicitly unrun without authorization; no token/code/key/body enters evidence.
- Root runs quality, focused/full tests, generated client checks and product/browser evidence; component stories and SDK mocks are reported separately from E2E.
- Promote current Toolkit/MCP OAuth/System Settings/Runtime Specs only for implemented reachable behavior. Set matching implemented dates only after completion and verification, then remove temporary phase plans.

## Checkpoint

Backend revision 3 was committed/opened and verified, but cleanup policy was then explicitly changed to fail-open. Its earlier tests do not verify the simplification. The in-progress UI patch is preserved separately; backend correction and regenerated contracts precede UI resumption. No unrelated request is dropped, no source is forced away, and no new material decision remains open for this policy.

Revision-4 backend integration now passes root-owned whole-subproject Ruff/format/typecheck, 146 related tests and 11,757 whole-backend tests (3 skips, 410.06 seconds). Regenerated Python/TypeScript contract checks and removal searches pass. The same independent reviewer is reviewing the stable integrated correction before updating #2222 and resuming UI. Details, invalidated earlier fixture evidence and remaining phase boundaries are recorded in the phase-1 plan.

The review's one rollback data-loss finding was corrected with a local credential-presence downgrade guard; provider failure never gates local disconnect or deletion. The post-correction root-owned related suite passes **149 tests**, including three real PostgreSQL rollback cases, and whole-subproject quality checks pass. Targeted same-reviewer re-review closed the finding with no residual issues; runtime/API source is otherwise unchanged from the successful whole-backend run.
