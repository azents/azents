---
title: "LLM Backend Phase 3: MIT Proxy Extension and Packaging"
created: 2026-10-28
updated: 2026-10-29
tags: [engine, inference, security, infra]
---

# Phase Execution Plan

- Phase: 3/3, final Proxy implementation plus the originally planned Phase 4 verification/Spec work, consolidated into existing Draft #2529.
- Branch/base: `feat/relay-proxy` -> `feat/relay-authority` (PR #2524); existing Draft #2529.
- Authority: approved relay-261028 Design r1 M1–M16, REQ-1–10, ADR-D1–D13. Phase-owned mechanisms M1, M6–M13, M16; integrated evidence supports M14.
- Design delta: None. The dependency-delivery exception is requester-approved in Requirements; server-prepared AWS sessions implement the existing server credential owner and final revalidation, not a second authority or mode.
- Owner: primary agent for all implementation, integration and validation.
- Exact independent reviewer: `/root/relay-reviewer`, read-only on the root-integrated completed diff; primary applies corrections.
- Deliverables: regular Proxy application/config/lifespan, request-bound auth and target/settings/credentials, closed ingress, MIT-covered published-wheel packaging and independently configurable chart.
- Non-goals: Worker/Runtime migration, new canonical backend or model store, user-managed keys, Proxy refresh/credential DB, custom distributed limiter, deployment/merge or billable inference.

## Current accepted execution clarifications

On 2026-10-29 the requester required officially published dependencies, then explicitly approved one exception: use the published LiteLLM dev release containing ChatGPT request-credential forwarding and switch to a stable containing that fix after equivalent checks. Use `1.109.0.dev1` from PyPI, never the prior Git source. Keep the exception reason and transition criterion beside the pin. No other prerelease or vendor-patch exception is granted.

Vertex's exact-credential/project SDK token cache is not a cached Agent authorization or an independently selected account. The prior blanket cache blocker was incorrect. The existing online admission and request-private extension binding remain authoritative. Verify A/B/A and denial while cache is warm; do not mutate SDK cache internals.

For Bedrock role configurations the server prepares an STS session outside transactions, then performs final authority revalidation before supplying the closed access/secret/session tuple. Do not supply role selection to the Proxy or permit an ambient fallback. Existing direct static-key configurations use their explicit keys without inventing a GetSessionToken requirement. Check session expiry at admission; no credential persistence or new refresh daemon is introduced.

Use current official Grok models, including `grok-4.7`, for acceptance. The prior old `grok-4` fixture's synthetic streaming does not establish a current Grok limitation.

## Workstreams and paths

| Workstream | Owner | Paths and interface | Validation |
| --- | --- | --- | --- |
| Published artifact | Primary | Proxy pyproject/uv.lock/Dockerfile/audit/NOTICE/README and CI build prerequisites | Registry wheel exact version/hash, no Git/Rust source build, Enterprise absence, installed inventory and nonroot image smoke |
| AWS preparation | Primary | shared authority DTO, server llm_authority/credential preparation, Proxy provider translator | Explicit source credentials and STS origin, no ambient lookup, session-token SigV4, expiry, failure/cancellation, preparation before final DB validation |
| Request/provider fidelity | Primary | Proxy ingress/auth/hooks/settings/history/tools/provider/transport and focused tests | Latest ChatGPT/Grok, Vertex account isolation, structured/tool/reasoning/search/image/cache/tier and cross-provider history matrix |
| Security/lifetime/operations | Primary | Proxy boundaries/config, existing authority routes/services, chart and Specs | Denied dispatch count zero, no secret diagnostics, no replay, early/late errors, disconnect/timeout/drain, restart and >1 replica render |

## Integration and completion order

1. Record the exception and full requirement/mechanism gap list.
2. Resolve the published dev wheel through uv, remove source-build prerequisites and update provenance/notices.
3. Complete AWS server preparation and closed contract; run focused server/contract/Proxy tests.
4. Complete all remaining approved deterministic fidelity/security/lifetime coverage. Keep live entitlement unavailable, not mocked as verified.
5. Root runs Ruff/ty/pytest, contract and server repository tests, Helm lint/render/tests, relevant CI-support checks and the actual official-package image build/smoke.
6. Freeze the integrated diff; obtain the same reviewer's full-phase review, correct actionable findings and rerun invalidated checks.
7. Update existing Draft #2529 and require new-SHA CI completion. Do not merge or deploy.
8. Complete the representative required E2E in this same final PR: existing public/Admin authentication and settings APIs, two Workspaces/accounts, actual authority via a verified forwarding-only TLS fixture and original Proxy image with only final provider transport controlled. Verify account/cap wire fields, target denial, settings change, Admin revoke and continued already-admitted first-delta stream. Owned paths add `testenv/azents/e2e/src/tests/required/test_llm_proxy.py`, its bounded fixture helpers/image handoff, and Proxy `scripts/e2e_fixture.py`. No DB writes or mocked binding/authorization are permitted. Promote owning Specs, run integrated Spec review/final QA, then remove plans only after evidence and final reviewer clearance. No additional validation-only PR is needed.

## Removal and absence obligations

Remove the unreleased Git pin, source provenance expectation and Rust source-build setup. Exclude Enterprise sources/packages and preserve original notices. Keep Worker adapters, integration storage, existing settings, usage persistence and issuer secrets out of Proxy changes. Verify absence of mirrored deployments, normal-auth fallback, ambient provider defaults, caller-selected credentials/endpoints, replay and whole-server env mounts.

## Evidence checkpoint before this continuation

Predecessor Phase 1 PR #2523 has 41 passing checks; Phase 2 PR #2524 has 37 passing/intentionally skipped checks. Draft #2529's prior development-Git candidate CI40782231789 passed, but is not published-package acceptance. Historical root checks: 248 Proxy, 50 contract, 74 server/repository/deletion, 102 chart, 62 CI scripts, 1514 Docker-free support tests. Prior image and real PostgreSQL/HTTPS/separate Proxy process journey used the old Git candidate and must not be relabeled as new-package evidence.

Official stable 1.106.6 feasibility isolated harness passed 255 tests with two native ChatGPT auth failures. The fix is in upstream PR41522/main and published dev1.109.0.dev1, absent from stable1.106.6. Current Grok4.5/4.6/4.7 nonstream/incremental-stream six-case probe passed. Vertex real JWT construction/A/B/A/denial and Bedrock static/session SDK probes passed against controlled physical wires. These are bounded feasibility evidence, not permission for live use or a complete phase review.

## Scope and final checkpoint rules

Requests must keep current Agent configuration authoritative. Final provider admission occurs after external preparation. Request cleanup releases Azents references without an impossible secure-memory-erasure claim. SDK credential caches are not an alternate admission authority. No reduced provider scope, maintained fork, custom provider backend or new operational mode is authorized. Report completed behavior, exact interfaces/commands/results, remaining live prerequisites and CI status; do not label incomplete deterministic cases complete.
