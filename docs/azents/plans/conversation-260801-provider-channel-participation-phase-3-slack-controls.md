---
title: "Provider Channel Participation Phase 3 — Slack Controls"
created: 2026-08-01
updated: 2026-08-01
tags: [external-channel, conversation, slack, backend, implementation]
---

# Provider Channel Participation Phase 3 — Slack Controls

## Phase Execution Plan

- Phase: `3 — Slack Provider-Native Controls`
- Branch/base: `feature/conversation-channel-participation-slack` → `feature/conversation-channel-participation-ingress`
- PR boundary: Implement authenticated Slack settings entry points, explicit interaction dispatch, signed conversation scope, provider-native setup/settings views, manifest guidance, and parent-channel delivery lowering while preserving provider-neutral participation and canonical execution authorities.
- Inputs: Approved `conversation-260801` Requirements, ADR, and Design; the multi-phase implementation plan; Phase 1 schema/domain foundation; and Phase 2 setup, ingress, replay, and parent Session contracts from PR 4.
- Deliverables: Bounded signed HTTP and Socket Mode Slash Command admission; `/azents settings`; invocation and Conversation settings message shortcuts; explicit callback/action/options/modal dispatch; signed opaque parent/thread settings metadata; setup location and canonical settings views and mutations; connected-Binding presence settings action; complete transport-aware Slack manifest guidance and existing-installation update notice; parent delivery without `thread_ts`; thread delivery with the root `thread_ts`; deterministic fake-provider coverage.
- Non-goals: Discord commands and controls; lifecycle invalidation and route-default replacement/clear; public management/OpenAPI/generated-client/Web projections; rollout enablement; integrated E2E fixtures; Living Spec promotion; and plan cleanup.
- Interfaces: The fixed Slack callback endpoint authenticates JSON and form callbacks before durable admission; interaction kind plus exact callback/action identifiers selects one typed processor path; signed metadata binds connection, parent or thread scope, route/default generation, setting or Binding generation, setup claim, principal, interaction, and page; trigger IDs remain in-memory only; participation services own committed settings and replay; provider delivery occurs after locks and transactions and cannot gate mailbox admission, wake, or AgentRun.
- Removal obligations: Replace selector-only interaction fallthrough with explicit typed Slack dispatch; replace bot/event-only manifest guidance with the complete command/shortcut/interactivity contract; replace inferred threaded parent delivery with explicit parent-versus-thread lowering.
- Absence verification: Parser and processor tests reject unsupported or mismatched callback/action families; repository search proves settings identifiers do not enter selector-only processing; manifest tests assert every required entry and transport-specific URL omission/presence; Slack delivery fakes assert parent calls omit `thread_ts` and thread calls retain it.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Slack admission and typed dispatch | `/root` | `services/external_channel/slack_http.py`, `slack_socket.py`, `interaction.py`, focused tests and minimal scheduler handoff wiring | Existing signature verification, durable interaction records, Phase 2 setup continuation | Bounded Slash form parsing, explicit message/block/options/view discriminators, typed handoffs, duplicate-safe processing | HTTP/Socket parser parity, signature, duplicate, unsupported-discriminator, and selector regression tests; Ruff; Pyright |
| Settings scope and provider-native views | `/root` | `interaction.py`, `slack_events.py`, Slack view/building helpers, participation/provider-control collaborators and tests | Phase 2 setting/location/replay services and principal authorization | Signed parent/thread scope, setup location choice, current settings view, mutations, stale/unsupported results, confirmations, presence settings action | Metadata tamper/staleness, parent/thread mutation, unsupported Slash thread scope, setup continuation, provider failure-independence tests |
| Manifest and installation guidance | `/root` | `management.py`, Slack management route/service tests, manifest constants | Fixed callback endpoint and Slack transport configuration | `commands` scope, `/azents`, invocation/settings message shortcuts, interactivity, HTTP request URLs, Socket URL omission, bounded existing-installation update notice | Manifest structure, identifiers, descriptions, transport URL, scope, and redaction tests |
| Slack delivery lowering and integration | `/root` | `channel_action.py`, `slack_events.py` or Slack client adapter, provider-control/presence builders, focused tests | Explicit parent Resource contract and existing thread delivery | Parent `chat.postMessage` without `thread_ts`; thread replies retain root target; connected presence exposes View session and Conversation settings | Fake Web API assertions, parent/thread regression tests, delivery failure/ambiguity independence, applicable backend suites |

- Integration order: Extend manifest constants and typed callback models; add signed scope and explicit processor dispatch; implement setup/settings views and mutations; add presence settings control; lower parent/thread delivery explicitly; integrate HTTP and Socket scheduling; add fake-provider and regression tests; run final validation.
- Independent review: `/root/conversation-260801-independent-reviewer` performs one read-only review against the immutable snapshot, this phase plan, owned diff, validation evidence, removal obligations, and non-goals. Required corrections are limited to Requirements/Design, security or data-loss, and material convention/interface defects; targeted re-review uses the same reviewer only when those criteria apply.
- Final validation: Changed-file `uv run ruff format --check` and `uv run ruff check`; `uv run pyright`; focused Slack HTTP, Socket, interaction, management, channel-action, provider-control, participation, and repository tests; applicable full External Channel and backend Pytest if feasible; `git diff --check`; docs validation through commit hooks; removal and identifier-routing searches.
- Scope-drift check: Compare the stable branch diff with this plan and Phase 3 Design outcomes; remove Discord, lifecycle, management API/Web/generated-client, rollout, integrated E2E, Living Spec, and cleanup work accidentally included.
- Context checkpoint: Record completed Slack entry points and mutations, changed typed interfaces, exact validation evidence, removal and absence proof, remaining Discord/lifecycle scope, relevant paths, and known risks before commit and PR creation.

## Phase Checkpoint

- Completed behavior:
  - Added signed HTTP and Socket Mode admission for `/azents settings`, the invocation shortcut, the Conversation settings shortcut, settings buttons, selector navigation, options callbacks, and modal submissions with explicit handler classification.
  - Added signed parent/thread settings scope, setup location continuation, authenticated settings resolution and mutation, and connected Session presence controls.
  - Added complete transport-aware Slack manifest guidance with the `commands` scope, slash command, message shortcuts, interactivity, HTTP callback URLs, and Socket Mode URL omission.
  - Added explicit Slack delivery lowering so parent-channel messages omit `thread_ts` and thread messages retain their root timestamp.
- Changed interfaces:
  - `SlackInteractionCallback` and `ExternalChannelInteractionHandoff` now carry an explicit typed handler and bounded settings fields.
  - Parent settings mutation requires both the signed setting identity and generation before any authorization, disconnect, update, or commit.
  - Slack Session presence rendering accepts an optional signed Conversation settings action.
- Removal and absence evidence:
  - Unknown callback/action families are classified as unsupported instead of entering selector processing.
  - Manifest tests assert the complete command/shortcut/interactivity contract and transport-specific callback URL behavior.
  - Lowering tests assert that parent payloads exclude `thread_ts` and thread payloads include it.
- Validation:
  - `uv run pytest -q --tb=short -o log_cli=false`: 3,796 passed.
  - Full External Channel/repository/core focused suite: 520 passed.
  - Final focused settings, interaction, manifest, and lowering suite: 89 passed.
  - `uv run pyright`: 0 errors, 0 warnings.
  - Changed-file Ruff format/check, `git diff --check`, and documentation index validation passed.
- Independent review:
  - `/root/conversation-260801-independent-reviewer` reported one stale parent-settings mutation warning.
  - The fix atomically validates the signed setting ID and generation before mutation. Targeted re-review reported no remaining Critical or Warning findings.
- Scope drift:
  - The diff remains limited to Slack provider-native controls, provider-neutral settings collaborators required by those controls, manifest guidance, Session presence, delivery lowering, tests, and this phase plan.
  - Discord controls, lifecycle replacement/clear, management API/OpenAPI/Web, rollout, integrated E2E, spec promotion, and cleanup remain in later phases.
- Remaining scope and risks:
  - Discord provider-native controls begin in Phase 4.
  - Existing Slack installations still require operator manifest refresh or equivalent manual configuration; lifecycle/API/Web guidance remains assigned to later phases.
