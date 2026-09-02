---
title: "Interactive Runtime Terminal Phase 3 Main Web Plan"
created: 2026-09-01
tags: [terminal, frontend, implementation, stacked-prs]
---

# Interactive Runtime Terminal Phase 3 Main Web Plan

- Snapshot: `terminal-260901`
- Requirements: `terminal-260901/REQ-3`, `REQ-6`, `REQ-7`, `REQ-10`
- ADR: `terminal-260901/ADR-D1`, `ADR-D3`, `ADR-D5`, `ADR-D6`
- Approved Design: `terminal-260901/DESIGN` revision `1`
- Approved mechanisms: `M2`, `M7`, `M8`, `M9`, `M10`, `M12`
- Base: `feature/terminal-260901-backend` / PR #1603
- Branch: `feature/terminal-260901-web`
- Design delta: `None`

## Scope

1. Regenerate and consume the additive TypeScript Public/Admin clients without manual generated-file edits.
2. Add `@xterm/xterm` and `@xterm/addon-fit` through pnpm lock resolution.
3. Add the Session-scoped Terminal container, binary/control wire handling, exact input/output sequencing, retries, resize coalescing, and cleanup.
4. Add stable-mounted desktop collapsed/docked/focused presentation and focused-only mobile presentation with accessible software keys.
5. Extend Agent, Workspace Profile, and infrastructure Profile settings with raw/effective Terminal policy surfaces for authorized managers.
6. Add localized copy, pure presentation tests, and real-component stories for required lifecycle and responsive states.

## Boundaries

- Do not remove `shell_enabled`; Phase 4 owns that cutover.
- Do not reconstruct policy or Runtime lifecycle client-side; consume backend projections and action flags.
- Opening or focusing Terminal never starts a stopped Runtime. Only the explicit existing Runtime Start action may do so.
- Keep the xterm host mounted across desktop presentation changes; mobile skips Docked.
- Do not persist, log, trace, or analyze Terminal bytes.
- Do not add E2E state setup or Living Spec changes; Phase 5 owns them.

## Validation

- Public/Admin TypeScript client generation and typecheck.
- Web format, lint, typecheck, unit tests, Storybook build, and production build.
- Focused browser/component verification for collapsed, docked, focused, stopped, reconnecting, replay-truncated, exited, policy-denied, Runtime-free, and mobile states.
- Independent stable-diff review before commit and PR creation.

## Phase Checkpoint

- Completed mechanisms: M2, M7, M8, M9, M10, and M12 with `Design delta: None`.
- Interfaces: generated Public Agent effective Terminal policy fields; generated-client-backed Terminal projection/ticket tRPC boundary; dedicated `azents.terminal.v1` browser WebSocket.
- Behavior: exact accepted/replay/input sequencing, retained unacknowledged input resend, cumulative output acknowledgement, bounded closed wire parsing, explicit disconnected termination, `ended` new-Terminal creation, rate-safe control coalescing, responsive stable-mounted xterm presentation, and ordinary-Chat restoration after policy or Runtime invalidation.
- Policy: infrastructure, Workspace Profile, and Agent raw settings remain independent; management surfaces show server-authored effective availability and denial scope.
- Validation: Web format, lint, typecheck, 209 tests, production build, and Storybook build; Admin format, lint, typecheck, 21 tests, and production build; Agent API Ruff, ty, 21 tests, deterministic OpenAPI dump, generated Public client checks, and `git diff --check`.
- Review: `/root/terminal-reviewer` completed the stable-diff review and two targeted re-reviews with no remaining findings.
- Removal boundary: `shell_enabled` remains intentionally present for Phase 4; E2E, Living Specs, implementation markers, and plan cleanup remain Phase 5.
- Scope drift: no missing approved behavior and no unauthorized material mechanism.
- Next branch/base: `feature/terminal-260901-shell-removal` based on `feature/terminal-260901-web`.
