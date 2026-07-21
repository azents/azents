---
title: "Generalized Sandbox Credential Injection — First Application with EnvVarToolkit Historical Decision Reconstruction"
created: 2026-04-21
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: sandbox-260421
historical_reconstruction: true
migration_source: "docs/azents/design/sandbox-credential-injection-2026-04-24.md"
---

# Generalized Sandbox Credential Injection — First Application with EnvVarToolkit Historical Decision Reconstruction

- Snapshot: `sandbox-260421`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/sandbox-credential-injection-2026-04-24.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### sandbox-260421/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Discussion Points and Decisions

Phase 1 completed in [Discussion #2875](https://github.com/azents/azents/discussions/2875). Core decision summary:

| # | Decision | Rationale |
|---|---|---|
| 1 | MCP first, sandbox shell last resort. Exceptions require justification document | reduce attack surface |
| 2 | Delivery is **env-only** (Phase 1). tmpfs/file out-of-scope | HTTP scripting reality; delivery form difference has little effect in threat model |
| 3 | allow all credential types, no separate admin approval. 2-step Info/Warning UI | toolkit configuration permission itself is manager/admin-or-above and acts as gate |
| 4 | Toolkit owns state machine — inject fresh env through `expose_env()` at `shell()` call time | no separate rotator/sidecar needed; extends existing ToolkitProvider pattern |
| 5 | Snapshot cleanup hook unnecessary | env naturally cleans up with process lifetime |
| 6 | Egress allowlist outside this design scope → [Discussion #2833 Thread 18](https://github.com/azents/azents/discussions/2833#discussioncomment-16654211) | coding agent profile design |
| 7 | UI 2-step (Info/Warning), prefilled safe TTL, default 3-month reminder | hard warning unnecessary, separate user responsibility |
| 8 | Audit: issue/use/revoke events + mitmproxy outbound (host+path, query string excluded), retention 90 days | essential for estimating damage after leakage, privacy protection |
| 9 | Docker local allows weakened profile, show K8s-only protection warning at registration | local dev convenience |

**First implementation order**: EnvVarToolkit → GitHub (installation token, dynamic renew) → AWS STS / GCP WIF

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
