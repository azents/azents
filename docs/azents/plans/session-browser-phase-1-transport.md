---
title: "Session Browser Phase 1 Execution Plan"
created: 2026-10-15
tags: [browser, runtime, implementation]
document_role: supporting
document_type: supporting-plan
---

# Phase Execution Plan

- Phase: 1/4 — shared transport authority and domain boundary.
- Branch/base: `feat/session-browser-261015-transport` → `main` at fdb34e87d.
- PR boundary: explicit Web/Browser authority types and wire variants, reusable shared stream core, behavior-preserving Web adapters/guards and tests. Include complete approved documents and multi-phase/phase plan; no Browser UI or product manager exposed yet.
- Inputs: [approved Design revision 2](../design/browsercmd-261014-session-browser.md), [Requirements](../requirements/browsercmd-261014-session-browser.md), [ADR](../adr/browsercmd-261014-session-browser.md), existing Runtime Control/Web stream behavior.
- Deliverables: shared code consumes only common transport identities/bounds; Web forwarding requires Web authority; Browser contracts cannot authorize existing Web exposure or arbitrary loopback forwarding. Generated wire outputs and exact fingerprint remain consistent.
- Non-goals: native browser implementation, Engine tools, Browser public admission, UI/Skill/files, Terminal/transfer transport redesign, compatibility aliases, additional Runtime ingress, Web policy change, merges/deployment.
- Interfaces: explicit WebStreamAuthority and BrowserStreamAuthority sharing only transport metadata; closed stream authority union/oneof. Web retains service/revision/identity/port/exposure; Browser owns concrete Session/task/page/current resource/input scope. Exact identities flow unchanged through gateway/accepting Control/Owner/Runner. Domain checks happen at domain admission and final consumer, not URL/query headers.
- Approved Design mechanisms: M3 and shared transport portion of M13; retain M2/M12 generation/access fence behavior.
- Authority references: prior browser-261014/ADR-D1; browsercmd-261014/REQ-2/4/8/9 and Design M3/M13; current Agent Runtime Control Spec.
- Design delta: None.
- Removal obligations: Web-only fields from common stream authority/proto/core; duplicate codec assumptions and Web transport authority confusion. Preserve service/exposure in Web domain with no deprecated wire fallback.
- Absence verification: repository symbol/codec reference search, no mixed nullable service/session authority, Web-domain variant assertions, wrong/unknown/unset variant wire tests, existing Web regression suites.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared authority/protocol/core and all dependent Web consumers | /root/browser-transport-implementation | proto/azents/runtime_control/v1/runtime_stream_session.proto; python/libs/azents-runtime-control; dependent backend runtime/stream and runtime_web_gateway; Runner web_session_dispatcher; related tests | Approved boundary and complete call-site map | Complete coherent authority replacement, wire generation, domain guards | Focused tests and quality checks, handed to root |
| Requirements/approval, plan, environment and integration | /root | docs/azents and Session-owned evidence/environment outside Git | Approved documents | Plans, regenerated/integrated evidence and phase checkpoint | docs_catalog, diff, root package checks and independent review |

- Integration order: authority types/wire schema → generated codecs/common consumers → Web-boundary adapters/current routing/capacity guards → focused regression → root checks → single stable read-only review → corrections/revalidation → commit/PR.
- Independent review: `/root/browser-feature-reviewer`; root requests only after all integrated implementation and validation finish.
- Final validation: configured runtime-control/Runner/backend ruff and ty; related stream/codec/bridge/pool/broker/Runner tests; docs_catalog validate; diff/absence checks. Existing required Runtime Web E2E remains regression obligation under the complete feature plan; record what is actually executed here.
- Scope-drift check: M3/M13 extraction is complete in touched surface; preserve all Web exposure/access/network/scheduling semantics. No application authority from common bytes, fallback/version map or unapproved Browser endpoint.
## Phase 1 Checkpoint

- Implemented: common TransportStreamAuthority and explicit Web/Browser closed union; strict shared codec; source-generated wire oneof; Web-only admission before routing/capacity/loopback; shared Browser peer identity support without Browser activation.
- Root-owned validation: runtime-control 347 tests plus full Ruff/format/typecheck and generator; Runner 419 tests plus full Ruff/format/typecheck; backend 575 related tests plus whole-project typecheck and changed-file Ruff/format. Focused backend boundary rerun is separately recorded in root execution evidence. Documentation validation and diff checks passed.
- Independent reviewer: `/root/browser-feature-reviewer`, exact base fdb34e87dacef7c061497168b44b2ef560771f55; no material findings. Reviewer independently ran 35 library/shared-state, 107 backend, 30 Runner dispatcher tests and byte-verified isolated generated outputs.
- Design delta: None. No current Browser tool/manager/UI/public consumer and no Web policy changes.
- Removal evidence: retired flat fields reserved with no decode fallback, all old direct constructors/duplicate codecs replaced, generic core has no service/exposure forwarding fields; wrong Browser variants have no Web capacity/routing/task effects.
- Runtime Control Spec updated only for reachable typed authority/shared contract and current Web-only consumers.
- Session devenv became ready after explicit private object-init helper/Runner build repair. Clone-to-ready 75.45 seconds, target not met; actual product Browser E2E not yet available and not claimed complete. No source data reset or production deployment.
- Next: commit this stable integrated phase and open PR to main before phase 2. PR identity and exact head are reported in the phase handoff. Phase 2 owns actual browser manager/commands/SDK/image and Agent tool integration.
