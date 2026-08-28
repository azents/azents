---
title: "Discord Quiet Work Presence Phase 2 Execution Plan"
created: 2026-08-28
tags: [discord, external-channel, implementation, plan]
---

# Discord Quiet Work Presence Phase 2 Execution Plan

## Phase Execution Plan

- Phase: `2/3 Gateway typing runtime`
- Branch/base: `feature/discord-quiet-work-presence-2-typing` →
  `feature/discord-quiet-work-presence-1-state`
- PR boundary: Fenced active-typing target projection and sustained public-SDK typing
  lifecycle inside the existing Discord Gateway connection owner
- Inputs: Phase 1 canonical Work schema/visibility lifecycle and PR #1546; approved
  `discord-260828/DESIGN` revision 1
- Deliverables: Active Discord conversational Work produces reconciled typing on its
  exact delivery channel; finish/ignore/disconnect/lease loss/shutdown stop renewal;
  reconnect/restart restores active targets; typing failures remain isolated
- Non-goals: Provider-fake E2E evidence, final Living Spec promotion, Slack typing,
  Scheduled Task typing, public API/UI/configuration changes
- Interfaces: One typed active-target projection per fenced connection; the
  `DiscordGatewayRunner` owns the concrete Client and accepts a typed target source;
  no direct Discord typing HTTP
- Approved Design mechanisms: `M4`, `M5`, `M6`
- Authority references: `discord-260828/REQ-1`, `REQ-2`, `REQ-5`, `REQ-6`;
  `discord-260828/ADR-D1`; current Gateway and provider SDK Specs
- Design delta: `None`
- Removal obligations: Replace the absence of a Discord typing lifecycle in the
  Gateway runtime; do not add a second persistent Discord client/runtime/credential
  owner
- Absence verification: Repository/static tests prove typing uses public SDK
  `Messageable.typing()`, only the current Gateway lease can project targets, no Redis
  correctness dependency or direct typing HTTP exists

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Active target projection | `/root` | External Channel repository/data/tests | Phase 1 schema | Distinct fenced delivery-channel targets from active Work | Repository tests, Ruff, ty |
| Public SDK typing lifecycle | `/root` | `discord_gateway.py`, typed runner contracts, focused tests | Target DTO/source interface | Per-channel renew/cancel/reconcile tasks on the existing Client | Gateway tests with explicit synchronization |
| Gateway manager integration | `/root` | `discord_gateway_manager.py`, tests, deterministic injected runner boundary | Projection and runner contract | Lease-fenced target source, reconnect and shutdown lifecycle | Manager tests, Ruff, ty |
| Independent review | `/root/quiet-presence-reviewer` | Read-only full phase diff | Stable implementation and checks | Severity-ranked findings or no findings | M4-M6 authority, lifecycle, SDK and failure review |

- Integration order: Target DTO/repository → runner contract → production public-SDK
  task registry → Gateway manager fenced source → deterministic tests → full affected
  validation
- Independent review: `/root/quiet-presence-reviewer`; review source-of-truth,
  lease/configuration fences, exact target resolution, shared-channel reference
  behavior, restart/shutdown cancellation, provider error isolation, public SDK-only
  boundary, and test determinism
- Final validation: focused Gateway manager/client and Work repository Pytest; affected
  External Channel Pytest; Ruff; format; `ty`; static provider SDK boundary tests
- Scope-drift check: M4-M6 complete; no new durable typing state, provider operation
  history, second runtime, Redis requirement, connection health mutation, E2E/spec
  promotion, or Slack/Scheduled behavior

## Phase 2 Checkpoint

- Completed behavior: full Gateway lease/AppClaim-fenced target projection; exact
  parent/thread delivery target grouping; active hidden and visible Work inclusion;
  public-SDK typing renewal on the existing long-lived Client.
- Changed interfaces: `DiscordGatewayRunner.run_connection()` requires a typed target
  loader; `ExternalChannelRepository` exposes an owned target projection returning
  stale `None`, valid empty `()`, or grouped targets.
- Lifecycle evidence: ready/resumed starts reconciliation; disconnect, removed targets,
  stale authority, Client stop, lease-owner cancellation, and shutdown cancel and await
  channel tasks.
- Failure evidence: typing HTTP/OSError remains task-local with bounded retry and
  sanitized logging; target-authority failure closes the current SDK lifecycle.
- Removal evidence: repository and static tests find no direct typing HTTP, no second
  persistent Discord Client/runtime, and no durable typing record.
- Validation: 707 External Channel tests and 41 focused Gateway/SDK-boundary tests
  passed; Ruff, format, `ty`, and `git diff --check` passed.
- Independent review: no findings; an additional 52 focused tests passed during review.
- Remaining scope: M8 provider-fake typing evidence, required E2E, Living Spec
  promotion, implemented snapshot markers, final validation, and plan cleanup.
- Risks: provider indicator expiry still permits a bounded visual tail after renewal
  cancellation; provider rate limits remain isolated presentation behavior.
- Design delta: `None`.
