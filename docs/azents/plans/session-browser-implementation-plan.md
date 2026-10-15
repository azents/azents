---
title: "Session Browser Implementation Plan"
created: 2026-10-15
tags: [browser, session, runtime, implementation]
document_role: supporting
document_type: supporting-plan
---

# Session Browser Implementation Plan

## Approved inputs and authority

- [Requirements](../requirements/browsercmd-261014-session-browser.md): REQ-1 through REQ-14, including the complete inherited baseline.
- [ADR](../adr/browsercmd-261014-session-browser.md): accepted D1-D4, unchanged earlier browser transport/resource/admission authorities.
- [Design](../design/browsercmd-261014-session-browser.md): revision 2, exact approved IDs M1-M17, requester approval 2026-10-14 at 22:06 KST.
- Implementation explicitly requested 2026-10-15 at 08:03 KST.
- Design delta: None.
- Primary owner: `/root`.
- Mandatory independent read-only reviewer for EVERY stable integrated phase: `/root/browser-feature-reviewer`.
- Research/implementation support stays within root-assigned non-overlapping paths; reviewer never edits. Root requests reviews, integrates all outputs, fixes findings, executes final checks and owns all PR/CI follow-through.

## Delivery shape

Four sequential reviewable PRs, titled `Session Browser [n/4]: <phase>`. Open each PR before starting the next phase, do not wait for prior CI to finish before preparing authorized later phase work. No merge, privileged infrastructure action or production deployment is authorized. A separate documentation-only PR is not planned.

| Phase | Branch / base | Approved mechanisms | Deliverable |
| --- | --- | --- | --- |
| 1 | `feat/session-browser-261015-transport` / `main` | M3, transport portion M13; retain M2/M12 current fences | Extract explicit Web/Browser authority variants and domain admission/dispatch boundaries through protocol, shared transport and existing Web consumers. Preserve all Web behavior; Browser public routes remain absent until phase 3. Include approved source documents and this plan. |
| 2 | `feat/session-browser-261015-runner` / phase 1 | M4-M12, M15, M17 | Product browser SDK/engine provisioning, Runner manager and Session/task/page/frame registry, current-target typed browser commands, actual input conflict admission, image/rawDOM/glance/capture and file interactions; Engine three tools and lowerer-compatible schema projection. |
| 3 | `feat/session-browser-261015-viewer` / phase 2 | M1, M2, M3, M9, M10, M12, M13, M16 | Browser-domain public admission/current revocation, authenticated common-stream Runner consumer, supporting-panel Browser UI with task/page selection, bounded frames and keyboard/pointer/IME; no takeover/return controls. Public clients source-generated. |
| 4 | `feat/session-browser-261015-verification` / phase 3 | M1-M17 | Managed Skill/references, complete real Engine/Web/Runtime E2E, file/model/publication and provisioning/network/sandbox evidence, final drift/spec audit and temporary plan cleanup. Mark implemented only after actual verified implementation. |

Local execution decomposition may refine within approved contracts; no new tool/control/permission/retention/configuration/compatibility mode. Move a dependent integration unit to the earliest coherent phase when necessary and record the reason, without changing Design authority.

## Interfaces and boundaries

- Command and stream authority derive concrete Session access separately from Runtime operation scheduling owner. Client/model input cannot select another Session/root/browser context.
- Shared stream contracts have explicit Web and Browser variants, preserving Runtime/Runner generation, Owner epoch, flow control and current policy fingerprints; no legacy fallback.
- Browser manager owns Session native state and current live resource incarnations; calls bind task/page/frame. Native state and old handles are separate.
- The public automation roles remain open/observe/act. Actual SDK actions are structured typed commands, not arbitrary JavaScript/MCP relay.
- Observe produces bounded scope-aware DOM/text and actual model imagery through existing image services; intentional original capture is not overwritten by model normalization.
- Input conflicts are real interaction boundaries; no persistent human-control flags or help registry. Conversation stop/continue with fresh observations remains normal Engine behavior.
- Native sandbox is used when supported; only specifically established native incompatibility allows sandbox-disabled startup. No generic exception downgrade or infrastructure mutation.
- Existing managed release Skill VFS and existing verified user-file publication remain sole delivery authorities.

## Removal obligations

Phase 1 removes Web service/port/exposure assumptions from common authority/transport, retains them in Web-domain authority/admission/forwarding, regenerates protocol outputs, and verifies wrong-variant rejection and existing Web tests. Phase 2 replaces system-only alleged SDK availability with actual uv/image-provisioned browser, without deleting profiles or adopting generic process TTL. No product MCP is installed to remove; add none. Phase 3 retains Session/Web/Terminal authority and normal panel dismissal/cancel semantics. Phase 4 removes phase/multi-phase plans after verified spec promotion. Prototype data is not migration input or shipped verification authority.

Absence checks: trace service/port/exposure reads to Web-only branches; search removed symbols/wire fields and all codec/import sites; dependency lock/image import/engine launch evidence; no MCP server/capability or human takeover/return API; no native profile copy or deletion. Generated sources are produced by established generators.

## Validation and prerequisites

Root final validation per phase uses configured ruff/ty/pytest in touched Python packages, TypeScript checks for phase 3+, protocol generation/checks, docs validation and exact stable diff review. Obtain actual command outputs; source inspection alone is not passing tests.

E2E-first matrix from Design: separate A/B accounts with same-Session reuse, multi-task closure/popup/frame, current Session access/revocation/read-only users, dialogue help/continue/independent work, conflicts/stale frames/IME/gestures, dialogs/upload/download/pre-armed events, DOM/glance/model image/capture originals/Exchange publication failures, cancellation/reconnect/replacement/non-replay, cross-replica shared transport/Web regressions, product browser sandbox supported/unsupported/generic-error classification, proxy enforcement, managed Skill projection/load/resume. Required synthetic tests fail on missing built capability rather than skipping it. Real external credentials/sites are optional and never replace synthetic required coverage.

Environment: Session-owned managed devenv prepared with current CLI and current daemon; existing private config is kept outside Git. Do not print tokens/cookies/env/database data. Record environment/image/SHA/prerequisite availability, build/check timings, scenario result evidence, transfer/capture hashes and bounded reasons. Perform actual browser/API and Runtime file/Shell plus stop/start preservation checks. Existing prototype 21 SDK assertions are diagnostic only, not integrated product acceptance.

## Specs and generated surfaces

Update Runtime Control/Persistence, Toolkit, File Exchange Storage and Session/conversation Living Specs for reachable changes; add current browser flow with real code paths. Run one complete spec review near final QA. Regenerate protobuf/OpenAPI/public/admin clients when their source contracts change. Migration/native-profile restoration is not planned; needing one triggers authority review.

## Checkpoints and completion

At each phase checkpoint record exact branch/base/PR/SHA, M coverage, changed interfaces/paths, removals, focused/root validation, reviewer finding resolution, CI and remaining risks. Freeze integrated diff before reviewer request. Reuse the exact reviewer across phases. Hold main/stack merge until explicit authorization, and keep dirty/unmerged evidence protected.

Initial checkpoint: source repository HEAD and origin/main both fdb34e87d; approved documents were local untracked files preserved in the Session worktree. Reviewer read complete authority and found no blocking contradiction. Current managed devenv listing had no environments. No implementation complete yet.
