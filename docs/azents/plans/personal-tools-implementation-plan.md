---
title: "Personal Tools Implementation Plan"
created: 2026-10-17
updated: 2026-10-17
tags: [toolkit, implementation, security]
---

# Personal Tools Implementation Plan

- Authority: [Requirements](../requirements/personaltools-261017-agent-access.md),
  [ADR D1-D3](../adr/personaltools-261017-agent-access.md),
  [approved Design revision 1](../design/personaltools-261017-agent-access.md).
- Approved mechanism IDs: M1-M11. Requester approved the complete Design and implementation on
  2026-10-17. Design delta: None.
- Implementation, integration, commands, corrections and phase progression: primary Agent `/root`.
- Exact independent read-only reviewer for every integrated phase: `/root/personal-tools-reviewer`.
- Source baseline: 4fffac9133934f5b85027b50842b1dc5a48da3b2. Implementation uses a dedicated feature
  branch and worktree.

## Delivery Phases

1. **Ownership and permission foundations.** Canonical owner/policy types, constrained schema and
   forward migration, owner-safe shared projections, personal persistence and All/Selected atomic
   operations. Includes authority documents and this plan; no extra design-only PR. M1/M2/M10/M11.
2. **Personal management and Provider authentication.** Owner-only CRUD/policy API, common Provider
   adapters, MCP/GitHub/Google personal setup targets and callbacks, generated clients. Depends on 1;
   M3/M4/M10/M11 plus M1/M2 interface consumption.
3. **User-root execution and source identity.** Personal effective sources, root identity and current
   allowance dispatch/export checks, namespace/lifecycle integration and Runtime parity. Depends on
   2; M5/M6/M7/M8/M11.
4. **Web journey and combined verification.** Account connections, Agent personal access, composer
   shortcut, common Provider views, locale/stories, cross-boundary deterministic E2E, Spec promotion
   and plan cleanup. Depends on 3; M3/M9/M11 and complete M1-M11 acceptance.

Use sequential PRs with `Personal tools [n/4]: ...` titles. Open each phase PR before beginning the
next. Subsequent branches base on the preceding phase branch. No merge or production deployment is
authorized. Track CI through all created PRs; correct failures without weakening gates.

## Interfaces and Integration

- Keep one canonical Toolkit identity; distinguish Workspace/Agent/User owners and preserve unchanged
  Workspace-only public contracts. Shared attachment/effective sources exclude personal records.
- A personal Toolkit has All/Selected policy; positive membership is independent of shared
  AgentToolkit attachment. All-to-Selected derives current eligible Agents in the transaction.
- Common services/Provider adapters own external work outside DB scopes. Owner-aware callback and
  current-grant checks retain existing lifecycle semantics and all Provider settings.
- User-root lineage, not sender/requester, selects personal authority. Current allowance is checked
  on each managed dispatch and new credential export; no recall of already exported credentials.
- Account and Agent views share policy authority. Session shortcuts navigate to the independent
  Agent page, not a Session-owned policy.

## Validation and Prerequisites

Primary Agent owns every integrated validation run. Each phase has format/lint/type checks and
focused database/unit/route tests appropriate to its boundary. Use the existing isolated test DB
fixture and current fake OAuth/Provider fixtures. Before full integration, prepare an owned isolated
integration environment; do not use another test run's data. Required
E2E verifies all Providers/auth families, two Users/Workspaces, Team/User/subagent roots, revocation
interleavings, shared parity and mobile routing. Live-provider acceptance remains separate.

Review only a stable integrated diff after focused validation; fix findings directly and rerun
invalidated evidence. Use the same reviewer for any material re-review. Never claim tests passed
without actual output.

## Removal, Specs and Rollout

Own each Design removal obligation in its activating phase: universal Workspace schema/domain
assumptions and shared owner predicates in 1; Workspace-only personal setup assumptions in 2;
prepared-source authority shortcuts in 3; obsolete prototype UI/defaults in 4. Retain legitimate
existing shared authority and credentials. Search for obsolete assumptions and prove absence through
negative/compatibility tests rather than deleting current shared workflows.

Specs impacted: toolkit, conversation execution, MCP OAuth, Google connection, applicable Agent and
Runtime/credential behavior. Update current behavior when it becomes reachable, and perform the
combined Spec review before final promotion. Set matching Requirements/Design implemented dates only
after integrated verification completes. Remove these temporary plans in phase 4 after final
verification; do not create an extra cleanup PR solely for process.

A normal coordinated schema/application rollout must avoid old binaries using the new User-owned
rows. No feature flag, dual write, relay or compatibility mode is introduced. Migrations are prepared
and tested locally only. Operational application and merge require separate authority.

## Checkpoints

- Initial: Design r1 M1-M11 approved; D1 common identity, D2 All/Selected, D3 parity resolved. No
  feature code or migrations applied yet. Phase 1 starts on the current dedicated feature branch.
- Phase boundaries: append completed behavior, stable interfaces, exact commands/results, review,
  PR/CI status, remaining scope and blockers. New product/material findings return to design; local
  implementation details stay within approved scope.
