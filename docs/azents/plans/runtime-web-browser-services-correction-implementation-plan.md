---
title: "Runtime Web Browser and Services Correction Implementation Plan"
created: 2026-09-13
updated: 2026-09-13
tags: [runtime, web, security, frontend, testing]
---

# Runtime Web Browser and Services Correction Implementation Plan

- Requirements: [runtimeweb-260913/REQ](../requirements/runtimeweb-260913-browser-services-correction.md)
- Decisions: [runtimeweb-260913/ADR](../adr/runtimeweb-260913-browser-services-correction.md)
- Design: [runtimeweb-260913/DESIGN](../design/runtimeweb-260913-browser-services-correction.md)
- Delivery shape: one focused PR on `feat/runtime-web-cross-browser-services-ui`
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M6, M7`
- Design delta: `None`

## Delivery Phase

One implementation phase owns the browser-neutral authentication correction,
Services navigation and interaction correction, generated contracts, migration,
current Specs, and regression coverage. These surfaces must change together because
old and new identity contracts are not a supported mixed-version steady state.

## Ownership and Review

- Implementation and integration owner: `/root`; no implementation is delegated.
- Independent read-only reviewer: `/root/phase1-readonly-review`.
- Review inputs: confirmed Requirements, accepted ADR, approved Design, phase plan,
  current Specs, and final diff.
- Review focus: Requirements coverage, security-boundary preservation, schema and
  generated-contract completeness, Services desktop/mobile reachability, and
  unauthorized mechanism detection.

## Workstreams and Interfaces

1. Gateway and identity authority
   - Remove Chromium, UA-CH, browser-profile, capability-probe, and browser-proof
     inputs while preserving raw Cookie cardinality, opaque-secret validation,
     Session/approval/Origin/CORS/Service Worker/transport boundaries.
2. Persistence, API, configuration, and generated surfaces
   - Drop the browser-profile column with an Alembic-generated revision; remove the
     field from models, repositories, services, Public API, settings, Helm, and
     generated clients.
3. Services navigation and interaction
   - Restore `services` in canonical Session panel navigation for desktop/mobile,
     visible polling, URL restoration, success-owned dialog dismissal, and honest
     Runtime evidence copy while reusing the existing panel and APIs.
4. Verification and specification
   - Update focused backend/frontend/E2E tests and Living Specs, run relevant quality
     checks and generation, then complete independent review and CI.

## Dependencies and Integration Order

1. Remove backend profile contracts and add the schema migration.
2. Regenerate Public API clients after the source OpenAPI changes.
3. Remove Main Web capability-probe/browser-profile callers.
4. Restore Services navigation and correct interaction state.
5. Update Helm, fixtures, tests, and Living Specs.
6. Run focused checks, independent review, full affected validation, commit, push,
   create the PR, and monitor required CI.

## Removal Obligations and Absence Evidence

- Chromium/version/client-hint admission: repository search and Gateway tests.
- Browser-profile persisted/API/config state: migration/schema/OpenAPI/generated
  surface checks and repository search.
- Main Web probe and browser-proof cookies/routes: route/source search and auth tests.
- Disconnected Services navigation: desktop/mobile navigation and URL restoration
  assertions.
- Premature dialog dismissal and inaccurate application-unavailable copy: component
  interaction tests and Storybook states.

## Validation Matrix

- Python: targeted Runtime Web policy, Gateway, repository, service, API, migration,
  and authority tests; ruff; formatter; configured type checker.
- TypeScript: targeted auth, panel navigation, Services container/component tests and
  stories; format; lint; typecheck; build.
- Contracts: dump Public OpenAPI and regenerate Python/TypeScript public clients.
- Helm: values/schema/template tests or repository-provided chart validation.
- E2E: Runtime Web Gateway authentication and Services management/navigation flows,
  including browser-neutral request evidence and desktop/mobile restoration.
- Specs: update Runtime Control, Chat Session Resync, and User Authentication current
  behavior; run spec review before marking the snapshot implemented.

## Rollout, External Actions, and Blockers

- Rollout is synchronized and roll-forward; no live cluster change is part of this
  work.
- Runtime storage remains 40 GiB.
- PR creation is authorized; merge is not authorized.
- No current material blocker or Design delta is known.

## Cleanup

After implementation, validation, spec promotion, review, and CI success, remove this
plan and the phase execution plan before the final completion commit so the immutable
snapshot, Living Specs, code, and tests remain the sources of truth.
