---
title: "GitHub User Account Toolkit Phase 2 UI"
created: 2026-10-08
tags: [github, toolkit, frontend, security]
---

# Phase Execution Plan

- Phase: 2/3 current UI and generated client integration.
- Branch/base: `feat/github-user-261008-ui` -> `feat/github-user-261008-backend` at `d3acb84eee5a70f7aee28df2ad3b7ab4a53830ba`.
- Dependency PR: [backend #2222](https://github.com/azents/azents/pull/2222), revised and pushed before resumption; no merge required.
- PR boundary: operable non-expiring Platform/BYOA user-account setup and details in the existing Toolkit UI, with local fail-open disconnect; no execution activation until phase 3.
- Inputs: confirmed [Requirements](../requirements/github-261008-user-account-toolkit.md), ADR-D1/D2/D4 and Design revision 4 M1-M10/M12; revised backend contracts and generated Public client. The preserved UI patch was restored from stash `141645cd7b3870583b8e66ef12a1e2cb5f047481` after rebasing its branch to the new backend. Keep the stash until the preserved work is safely committed.
- Deliverables: five auth choices; redacted saved registration editing; current Platform availability; saved-Toolkit popup/callback/review/confirmation; personal/multi-org observations; local disconnect without cleanup status/retry; localized accessible pure UI stories and focused state tests.
- Non-goals: catalog/layout redesign, new credential hub/navigation/role, PAT default change, refresh/proxy, cleanup actor/retry/status, production/provider changes, Worker/Runtime activation or product E2E claims.
- Interfaces: generated Public SDK through tRPC; canonical allowlisted user connection summary without cleanup fields; exact ownership context; `github_user.<attempt_id>.<nonce>` state prefix; fixed `/oauth/github/callback`; completion event contains only fixed type and attempt ID, then opener queries server review.
- Approved Design mechanisms: M1, M3-M5, M7-M9, M12; presentation of M2/M10. M6 execution belongs to phase 3. M11 is retired.
- Authority references: `github-261008/REQ-1..13`, ADR-D1/D2/D4, DESIGN revision 4; retained catalog/detail/immediate-mutation and Runtime opt-in contracts.
- Design delta: None.
- Removal obligations: remove all preserved cleanup pending/retry controls, state, tRPC procedures, summaries and locale/story fixtures; replace three-mode-only assumptions and unconditional Platform choices while retaining GitHub/PAT/BYOA, old installation callback and generic MCP OAuth.
- Absence verification: source search finds no GitHub cleanup pending/retry dependency; generated SDK is used without raw product API calls; five-mode/Platform availability/projection and old-mode immediate-save regressions pass; no token/client-secret/private-key in public summaries or callback messages.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| UI lifecycle/forms/details/callback/tRPC/locales | `/root` | Toolkit feature files, applicable Agent management files, GitHub callback entrypoint, `trpc/routers/github-user.ts` and narrow Toolkit router integration, en-US/ko-KR/ja-JP/fr-FR | revised phase-1 contracts | current UI, pure stories/state tests, fail-open local completion copy | focused format/lint/typecheck/node/story checks |
| Integration and rendered validation | `/root` | tracked plans, generated contracts, evidence and agreed narrow supporting corrections | completed UI lane | integrated accessible/localized UI without source or authority drift | root-run web quality/build/tests and trustworthy component renders |

Localization support reuses the completed backend roles for bounded draft-only work: `/root/github-user-persistence` (Korean), `/root/github-user-service` (Japanese), and `/root/github-user-provider` (French). They write only outside-project translation drafts from the fixed English key shape; `/root` checks fidelity and `/root` remains the sole owner of actual locale file edits. These roles do not change backend source, request review or commit.

## Lifecycle and Verification Contract

- Save new registration immediately before OAuth. Toolkit presence is not account authorization success. Confirm verified account identity and existing sharing scope before activation; preserve working authorization until confirmed replacement.
- Strip blank unchanged BYOA fields individually. Compatible saved registrations can omit write-only values; new or incompatible source/App identity requires its own values. Never inherit another registration's secrets.
- Persist the exact originating Toolkit/Workspace/optional Agent context with existing Mantine session-storage hooks before synchronously reserving the popup. Its initial storage clone is not a live context update.
- Accept completion only from current origin, the exact non-null reserved popup and current attempt. Notify fixed event and attempt ID only, never code/state/token/account payload. Query review from the server.
- Confirmation, cancellation, disconnect and deletion may commit locally before an unexpected request interruption. Invalidate ownership-specific Toolkit/status/review/access queries on settled as appropriate. Expected provider cleanup failure is normal local success, with no retry/pending UI and no provider-revocation guarantee. Do not roll back to the retired account.
- Hide unavailable Platform choices only, not the GitHub catalog tile or PAT/BYOA choices. Distinguish absent/incomplete configuration and query/provider errors; saved missing-Platform connections retain their identity/settings and actionable recovery.
- Group/deduplicate paginated access by installation/repository identity. Keep unknown/read-only/partial access explicit, and do not label selected toolsets as grants or a repository allowlist.
- Static stories cover connection/confirmation/reconnect/local disconnection, popup blocked/closed, stale/wrong context, personal/two-org partial access, mobile overflow and keyboard focus. State tests cover parsing, origin/source/attempt rejection, credential omission, projection and pagination. Locale keys and natural user-facing copy align across four current locales.
- Preserve existing immediate-save and catalog/details hosts. Apply operational utility copy and current Mantine/container conventions; no new decorative surface or product flow is authorized.
- Browser/API/Worker setup-to-execution evidence remains phase 3. Component renders and SDK fixtures are not live provider or product E2E evidence.

- Integration order: revised generated contracts -> remove superseded cleanup state/tRPC/UI -> complete forms/context/callback/details/availability/locales/stories -> root validation -> stable same-reviewer review -> root corrections -> commit and dependent PR.
- Independent review: `/root/github-user-reviewer`; only root requests review after all workstreams and root integrated validation are complete. Implementation owners do not commit or request review.
- Final validation: root-owned filtered web format/lint/typecheck, relevant node and Storybook tests, web build and trustworthy rendered component states. Record failed/skipped evidence explicitly; do not claim success from the preserved unfinished patch.
- Scope-drift check: complete authorized UI and removal coverage, unchanged old defaults/sharing/flows, no new material mechanism or later-phase execution code.
- Context checkpoint: backend commit `d3acb84ee` is pushed to #2222 with same-reviewer findings closed. Root backend full run passed 11,757 tests before the narrow rollback guard; post-correction related tests passed 149, quality checks and commit hooks passed. The backend's 41 reported CI checks are passing/skipped with none pending or failed. UI was restored without loss; root completed the remaining implementation directly, with the prior implementation role interrupted and no implementation descendants active. No merge, deployment or live credentials are authorized.

## Root Integration and Validation Checkpoint

- Four locales were integrated and reviewed for naturalness and faithful account delegation/fail-open wording. Root localized registration validation and supplied accessible loading status without changing layout or ownership behavior.
- Root whole-web format, lint and TypeScript checks pass. All **423 Node tests pass**, including locale structure, credential omission/hydration, callback context/message parsing and old installation Runtime-warning preservation.
- Root Next production build and static Storybook build pass after the final accessibility correction. Existing build/plugin chunk-size and module-type warnings are reported separately from failures; no unrelated package/config change was introduced.
- A dedicated named `agent-browser` session rendered **45 synthetic component story states** at 1280×900, with completed renderer state, meaningful content or accessible loading status, and no horizontal overflow. Renderer/play-function metadata is not a standalone test-runner pass or product E2E claim.
- Root inspected 390×844 native mobile captures for replacement confirmation and partial personal/multi-organization access. Sharing impact, non-guaranteed revocation and confirmation controls remain visible; no horizontal overflow was found. This is real component rendering with synthetic props, not a live provider account.
- Browser launch required the container-only `--no-sandbox` flag in this dedicated local QA session. No production browser/security configuration or another agent's browser session was changed. The local static preview server was restarted after the Runtime expired its idle process.
- Earlier formatting, test-schema/key-type and unnamed loading-state issues were corrected and affected checks rerun. Preserved unfinished-patch results are not used as final evidence.
- The same mandatory reviewer found one popup-handoff replay issue. Root made acceptance consume only the exact reserved popup in the parent, kept the child's active popup reference, cleared unaccepted handoffs on Details close and guarded new authorization while setup is pending. New explicit user authorization reserves a fresh `_blank` window so its opener-cloned context cannot reuse another attempt's stored return context.
- Two new pure handoff regression cases cover accepted open/closed popups, no retained handoff after Details remount, preservation of a newer reservation against a stale acknowledgement and a fresh explicit handoff consumed once. They are state-contract evidence rather than complete hook/product E2E.
- Dedicated local browser evidence confirms two explicit `_blank` reservations produce distinct windows with their respective Toolkit/return-path context clones. No provider URLs or credentials were used.
- Post-correction root checks pass: whole-web format/lint/typecheck, **425 Node tests**, Next production build and static Storybook build. Earlier 45-state synthetic render evidence remains applicable to unchanged component presentations; popup browser evidence addresses the changed browser-reservation semantics. The same reviewer completed targeted read-only re-review and closed the popup lifecycle finding with no residual issues. All phase-2 review findings are resolved.
