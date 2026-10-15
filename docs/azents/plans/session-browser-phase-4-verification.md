---
title: "Session Browser Phase 4 Verification and Managed Skill"
created: 2026-10-15
tags: [browser, session, runtime, implementation, verification]
document_role: supporting
document_type: supporting-plan
---

# Phase 4 Execution Plan

- Phase: 4, managed Browser Skill and complete delivery verification.
- Branch/base: `feat/session-browser-261015-verification` →
  `feat/session-browser-261015-viewer` at `c78a5cd3043e014b49d9f4316a1f7a7527bcc63e`.
- PR boundary: `Session Browser [4/4]`, based on [Phase 3 PR #2268](https://github.com/azents/azents/pull/2268).
- Inputs: [Requirements](../requirements/browsercmd-261014-session-browser.md)
  REQ-1–15, accepted [ADR](../adr/browsercmd-261014-session-browser.md) D1–D5,
  approved [Design](../design/browsercmd-261014-session-browser.md) revision 3
  M1–M18, current [flow](../spec/flow/session-browser.md).
- Approved mechanisms: M14 Skill packaging; M6/M7/M11/M12/M15 file/model,
  lifecycle and failure validation; M17 provisioning/network/sandbox evidence;
  complete M1–M18 and REQ-15 drift/acceptance verification.
- Deliverables: one release-bundled Browser Skill with focused references,
  validated examples/projection/load/resume; real Engine → managed Runner →
  original capture → model FilePart → verified user publication evidence;
  complete scoped acceptance report, current Specs and final plan cleanup.
- Non-goals: new permissions, persistence/retention, public endpoints, Runtime
  topology, browser backends, configuration modes, automatic input replay,
  profile reset, arbitrary JavaScript, deployment or merging.
- Interfaces: existing three tool schemas and strict Browser DTOs; existing
  immutable `release:azents` VFS projection and `load_skill`; current
  RuntimeImageReadService/ModelFile/FilePart and `present_file`/Exchange.
- Design delta: None.
- Removal obligations: remove the feature multi-phase and phase execution plans
  after complete verified spec promotion. Obsolete known-input replacement was
  removed in Phase 3 and must remain removed. No profile/data migration.
- Absence verification: no references to removed plans at cleanup; no global
  input-value collection/replacement, browser MCP, persistent takeover mode,
  automatic effect replay, profile deletion or new delivery authority.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Managed Skill | root | `python/apps/azents/src/azents/resources/vfs/global/skills/browser/`, related existing VFS/Skill/tool tests | Phase 3 schemas | Release Skill and focused tool/file/help references | Frontmatter, package projection and real load, example validation against all supported lowerers, old-projection preservation |
| Full file journey | root | `testenv/azents/e2e/src/tests/web/public/`, focused support/aimock fixtures, affected existing Browser/file tests | Current managed Runner and existing file services | Actual original PNG, model image and verified publication results | Normal user-facing setup; exact file/hash/scope assertions; no DB writes, forged authority or secret output |
| Final corrections and evidence | root | Narrow existing Browser/transport/file paths only when a reproduced failure requires it; supporting QA report | Prior checks and CI | Resolved concrete failures and bounded evidence | Root affected integrated checks; same reviewer for high-risk corrections |
| Specs and cleanup | root | Relevant `docs/azents/spec/`, snapshot completion dates and feature plans | Complete verified implementation | Current Specs, immutable completed snapshot, obsolete plans removed | One final spec review, catalog/reference checks and complete-diff independent review |

## Integration and review

1. Package the Skill against the final schemas and verify release projection.
2. Complete representative file/model/publication E2E and scoped provisioning,
   network and sandbox evidence; investigate concrete failures without weakening
   assertions, extending acceptance deadlines or adding fallbacks.
3. Check Phase 3 CI in the background. Current CI exposed a render-to-ACK race:
   keyboard/composition events from the same attachment/navigation can reach the
   connection after its displayed ACK advances but before React rerenders. Rebind
   these non-spatial actions to the latest actually displayed ACK only when the
   target/navigation/dimensions are identical, preserving exact-frame spatial
   fencing and no replay. Add focused regression and inspect content-free native
   capture failure categories rather than retrying effect-bearing input.
   CI's subscription-usage log regression was traced to Phase 3 overriding the
   shared public API fixture's Runtime environment to `local`, which changed
   deployed JSON logging. Restore the shared fixture's deployed environment and
   compose Browser transport from the existing ordinary Control endpoint/CA and
   explicit insecure opt-in, like the existing API clients. Keep the Browser-only
   proof/audience and fail-closed missing-TLS default; no new setting, automatic
   downgrade, source bypass or credential reuse. Validate deployed JSON logging
   and normal Browser ingress together, and require targeted security re-review.
   Its prepared local E2E completed with
   `4500 Browser is unavailable` at the final revocation assertion instead of
   `4401/4403`; that remains unresolved and is not acceptance evidence.
4. Consolidate all requirement/mechanism evidence and limitations. Run final
   spec review, set completion dates only after verified delivery, and remove
   temporary feature plans after promotion.
5. Freeze the complete integrated phase diff. Root requests the single existing
   read-only reviewer `/root/browser-feature-reviewer`; root applies corrections,
   runs invalidated checks, commits and opens the final PR, then monitors all
   stack CI. No merge/deployment is authorized.

## Execution checkpoint

- Phase 3 PR #2268 is open and CI is running. The requester explicitly directed
  CI-first parallel delivery rather than waiting for local E2E before opening it.
- Phase 3 independent full review and targeted re-review passed. Root checks:
  shared 450, Runner 473, backend 469, Web 521, 40 real component stories, staged
  hooks; current prepared images match 63 Runner/shared and 2,467 backend/shared
  Python sources. Image SDK probes passed 26 checks.
- Hosting Runtime storage exceeded its 40 GiB EmptyDir limit and was evicted.
  The requester authorized one unused build-cache cleanup; it reclaimed 4.59 GB
  while preserving images, containers and volumes. No infrastructure mutation.
- Root owns all implementation and validation. Phase 4 source work starts only
  after this plan, with unchanged material authority and Design delta None.
