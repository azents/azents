---
title: "Provider SDK Migration Phase 2 Delivery and Files Plan"
created: 2026-08-09
updated: 2026-08-09
tags: [external-channel, slack, discord, sdk, implementation]
---

# Provider SDK Migration Phase 2 Delivery and Files

## Phase Execution Plan

- Phase: `2/3 — Discord delivery/files and Slack byte transports`
- Branch/base: `azents/provider-sdk-migration-delivery` → `azents/provider-sdk-migration`
- PR boundary: public SDK message/thread/edit/delete and metadata operations plus exact direct byte transports G2-G5
- Inputs: phase 1 request-scoped `DiscordSDKClientFactory`, bounded projections, error mapping, confirmed `external-260809/REQ`, accepted ADR, approved Design revision `1`
- Deliverables: Discord SDK-owned text delivery/thread/title/edit/delete and attachment metadata; operation-specific G2 Discord multipart upload and G3 Discord attachment byte transport; Slack SDK API operations separated from G4 private download and G5 presigned upload byte transports; updated dependency wiring and focused tests
- Non-goals: deterministic Gateway runner replacement, private SDK import removal, final provider-fake/E2E conversion, Living Spec promotion, implemented dates, plan cleanup
- Interfaces: extend `DiscordSDKSession` with bounded delivery and metadata methods; direct transports expose only one approved gap operation each; retain existing domain results, deadlines, nonces, exact-length streams, commit-before-I/O, one-attempt, and no-replay contracts
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M7, M8`
- Authority references: `external-260809/REQ-1..REQ-7`; `external-260809/ADR-D1..D4`; `external-260809/DESIGN` M1-M5 and M7-M8; current External Channel delivery, file, and provider-ingress Specs
- Design delta: `None`
- Removal obligations: remove SDK-supported Discord delivery/file metadata raw routes, generic Discord delivery HTTP request surface, and general Slack HTTP injection from SDK-supported API operations; retain only G2-G5 direct byte transports
- Absence verification: no Discord channel/thread/text/edit/delete or source-message metadata route literals outside G2/G3 modules; Slack direct HTTP limited to authenticated private-file bytes and provider-issued presigned upload bytes; no second SDK or compatibility fallback

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Discord SDK delivery | root | `discord_sdk.py`, `discord_delivery.py`, `channel_action.py`, related tests | phase 1 SDK lifecycle | public typed channel/thread/message create/edit/delete/title operations with nonce and bounded results | delivery lifecycle, ambiguity, nonce, relationship, and error tests |
| Discord file boundary | root | `discord_files.py`, `file_transfer.py`, related tests and narrow G2/G3 transports | Discord SDK delivery | SDK metadata refresh plus exact multipart/CDN byte gaps | identity, origin, redirect, size, chunk, and closure tests |
| Slack byte split | root | `slack_events.py`, `slack_sdk_client.py`, `channel_action.py`, `file_transfer.py`, related tests | existing Slack SDK factory | SDK API calls with G4/G5 operation-specific byte transports | file info, download, upload, exact-length, and error tests |
| Removal and wiring | root | dependency providers and obsolete route fixtures in owned paths | preceding workstreams | narrow collaborators only; obsolete generic clients removed | grep/AST absence scans, focused suite, `git diff --check` |

- Integration order: extend SDK interfaces → Discord text/thread delivery → Discord metadata and G2/G3 transports → Slack G4/G5 split → dependency wiring → obsolete path removal → focused validation
- Independent review: `provider-sdk-reviewer`; read-only review against confirmed Requirements, accepted ADR, approved Design M1-M5/M7-M8, this phase plan, current Specs, and full phase diff; report only correctness, security/data-loss, contract, convention, interface, and material removal findings
- Final validation: Ruff format/lint; `uv run ty check --error-on-warning`; focused Discord delivery/files, Slack conversation/file, channel action, and file-transfer tests; complete External Channel unit suite; `git diff --check`; direct-route/second-SDK scans
- Scope-drift check: every approved Phase 2 SDK replacement and G2-G5 boundary is present; no Gateway test composition, E2E fixture, Living Spec, persistence, public API, new dependency, fallback, or runtime mode is added
- Context checkpoint: record SDK methods added, exact G2-G5 transports retained, removed generic clients/routes, dependency changes, validation and review evidence, remaining Phase 3 fixture/private-import/spec work, risks, and blockers before commit and PR creation

## Completion Checkpoint

- Added public `discord.py` SDK methods for typed message, Thread, edit/delete, and attachment metadata operations with request-scoped lifecycle, explicit 20-second delivery/metadata deadlines, bounded projections, Guild/channel/parent validation, and SDK exception classification.
- Retained G2 only for exact-length streamed Discord multipart file messages and G3 only for allowlisted Discord CDN HEAD/GET bytes. Midstream source failures remain ambiguous and are never replayed.
- Split Slack SDK API operations from G4 authenticated private-file bytes and G5 provider-issued presigned upload bytes. Both transports validate allowed origins and preserve exact-length, bounded-stream, ambiguity, and closure behavior.
- Removed the generic Discord delivery request surface, Discord source-message metadata route, and general Slack HTTP ownership from `SlackConversationClient`; dependency providers now construct narrow SDK factories and G2-G5 transports.
- Absence scan found one Discord API message route in G2, Discord CDN byte access in G3, and `httpx` ownership only inside G4/G5 transport classes. No second SDK or compatibility fallback was added.
- Validation: Ruff lint/format passed; `ty check --error-on-warning` passed; External Channel suite collected 496 tests with 493 passed and 3 skipped only because Docker was unavailable; `git diff --check` passed.
- Independent review found two high ambiguity-classification issues in G2/G5. Both were corrected to `unknown/provider_ambiguous` with midstream regression coverage; targeted re-review passed.
- Remaining Phase 3 scope: injected deterministic Gateway/SDK fakes, private SDK import/global endpoint override removal, static repository checks, Docker-backed E2E/full validation, Living Spec promotion, implemented dates, and plan cleanup.
- Design delta: `None`; persistence, public API, production dependency, configuration, and runtime-mode scope remain unchanged.
