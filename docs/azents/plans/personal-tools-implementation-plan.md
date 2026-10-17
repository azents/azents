---
title: "Personal Tools Implementation Plan"
created: 2026-10-17
updated: 2026-10-17
tags: [toolkit, implementation, security]
---

# Personal Tools Implementation Plan

- Authority: [Requirements](../requirements/personaltools-261017-agent-access.md),
  [ADR and scope clarification](../adr/personaltools-261017-agent-access.md),
  [approved Design revision 2](../design/personaltools-261017-agent-access.md).
- Approved mechanisms: M1-M11. The requester instructed immediate corrective development after the
  complete revision 2 approval brief on 2026-10-17. Design delta: None.
- Implementation, integration, validation, corrections and phase progression: `/root`.
- Single independent read-only reviewer: `/root/personal-tools-reviewer`; root applies findings.
- Initial baseline: `4fffac9133934f5b85027b50842b1dc5a48da3b2`. Existing unmerged feature phases used
  a global-scope interpretation that is superseded by the confirmed Workspace boundary. Their test
  successes remain historical evidence, not proof of the corrected scope.

## Corrected Delivery Phases

1. **Ownership and permission foundations.** Correct the existing foundation layer: mandatory real
   Workspace in User ownership, owner+Workspace predicates, scoped All/Selected intents, constrained
   positive membership and corrected unmerged migration. M1/M2/M10/M11. Current correction branch
   `fix/personal-tools-workspace-foundation-261017` starts at Phase 1 commit
   `e5add532e987645bc5228a833a4e43f25da55f45`; detailed contract is
   [foundation correction plan](personal-tools-workspace-foundation-correction.md).
2. **Personal management and Provider authentication.** Integrate the corrected foundation into the
   existing management phase; require authorized Workspace context for CRUD/access/tests and every
   Provider setup, callback, refresh and publication target. Regenerate public interfaces/clients.
   Preserve all Provider options and existing shared/Agent contracts. M3/M4/M10/M11 consuming M1/M2.
3. **User-root execution and source identity.** Integrate scoped personal selection and exact current
   parent/provider admission, discovery/refresh/publication/export checks. Canonical root User and
   execution Workspace must both match. Preserve namespace/lifecycle and Runtime parity. M5-M8/M11.
4. **Workspace Web and complete acceptance.** Preserve reusable common owner-form work from the dirty
   Web draft, replace account-global routes with Workspace personal management, correct Toolkit-side
   same-Workspace Agent selection and Agent/composer entry/return, and improve visual quality in real
   shells. Finish locales/stories, deterministic API/Worker/Web matrix, Spec promotion and cleanup.
   M3/M9/M11 and complete M1-M11 acceptance.

Keep reviewable layer boundaries and existing PR provenance. Open each corrected phase as a PR or
update its existing phase PR before starting the next implementation layer. Do not rewrite another
worktree or discard the current Web draft. Rebase/retarget the dependent stack only after corrected
foundation review/validation. Track exact-SHA CI across the final corrected stack. No merge or
production migration/deployment is authorized.

## Fixed Interfaces and Removal Boundaries

- One canonical Toolkit ID and common Provider/grant platform. Shared, Agent and User owners all
  carry the real Workspace; only personal ownership adds the authenticated owner User.
- Every personal repository read/lock/write carries both User and Workspace. First restriction derives
  the full eligible Agent set inside that Workspace in the transaction. Positive membership constrains
  both its canonical parent scope and Agent scope; no cross-Workspace personal binding is retained.
- All/Selected is independent per Toolkit. Both editors issue intents against that authority; filtered
  read lists are not replacement writes. Own policy requires ordinary Workspace/Agent access but no
  shared Toolkit-manager/AgentAdmin role solely for personal settings.
- Common Provider operations perform external work outside DB transactions and re-admit the exact
  current User/Auth Session/Workspace/Toolkit before final writes. Shared callbacks remain unchanged;
  obsolete personal-global targets are removed rather than silently upgraded.
- Canonical durable User-root and execution Workspace select personal capabilities. Sender, viewer,
  broker and Tool args do not. Current scope/allowance gates managed dispatch and later export; already
  admitted calls/tokens retain their existing lifetime and shared-resource behavior.
- Workspace and Agent views edit the same per-Toolkit authority. Remove account-global personal
  routes, Workspace search/groups and unrelated prototype defaults. Keep the mobile Session header
  unchanged and reauthorize same-Workspace source returns.

## Validation and Prerequisites

Root runs each phase's format/lint/configured types, focused DB/route/Provider and migration regression,
client generation consistency and integrated checks. Mandatory product verification uses owned isolated
real API/persistence/Worker/Web and deterministic fake Providers, with two Users and Workspaces,
matching names, same-User A/B separation, independent Toolkit policies, Team/User/subagent roots,
stale callbacks, withdrawal interleavings and Runtime export parity. Missing required fake prerequisites
fail, not skip. Live Provider checks remain optional and separately reported.

Real-component stories own presentation/state permutations, keyboard, search/cancel/error/conflict,
mobile navigation/page/menu and long-list fixed actions. Render actual Workspace/Agent-shell context
with real theme/fonts; prior checkbox stress captures were not accepted visual quality. Old tests and
screenshots cannot stand in for corrected scope or complete product acceptance.

Request the fixed reviewer only after the complete layer's integrated diff is stable and root validation
is complete; root directly resolves findings and reruns invalidated checks. Do not weaken gates,
enlarge timeouts or claim unexecuted checks.

## Specs, Migration and Closure

Update reachable Specs as each corrected layer becomes current, and perform final combined Spec review
before promotion. Set matching Requirements/Design implemented dates only after complete acceptance.
Remove feature implementation/phase plans after validated promotion, not before. Do not create extra
cleanup/design-only PRs solely for process.

Correct the unmerged migration from the supported pre-feature baseline without relabeling an already
applied draft schema or guessing a Workspace for incompatible global rows. Preserve data and diagnose
such state explicitly. Existing shared/Agent resources keep IDs/grants/attachments/namespaces. Use the
normal coordinated schema/application rollout; no flags, global fallback, dual write or new Runtime.

## Current Checkpoint

The correction worktree is separate from the preserved uncommitted Web draft. Foundation scoped
repository/ownership tests and migration/model alignment are being executed before fixed-reviewer
review. Management, execution, Web redesign and full product acceptance remain pending. No corrected
phase commit/PR/CI or merge/deployment completion is claimed here.
