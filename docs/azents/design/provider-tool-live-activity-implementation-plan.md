---
title: "Provider Tool Live Activity Implementation Plan"
created: 2026-07-16
updated: 2026-07-16
tags: [backend, engine, frontend, llm, testing]
---

# Provider Tool Live Activity Implementation Plan

## Feature Summary

Implement the provider-neutral live activity contract defined in [Provider Tool Live Activity Design](./provider-tool-live-activity.md) and [ADR-0163](../adr/0163-normalize-provider-tool-live-activity.md). Adapter output normalizers will translate observed native hosted-tool lifecycle events into one canonical stream projection. The existing live Event surface will expose activity to the generic provider-tool UI and replace it with durable history on completion.

## Stack Prefix

`Provider tool live activity`

## PR Boundaries

### PR 1 — Design

- Add ADR-0163.
- Add the approved feature design and E2E-first test strategy.

Dependency: `main`.

### PR 2 — Implementation plan

- Add this phased plan.
- Record validation, fixture, spec, rollout, and cleanup requirements.

Dependency: PR 1.

### PR 3 — Backend provider-neutral activity pipeline

- Replace the weak stream projection record with a typed discriminated union.
- Add provider-tool observation and shared lifecycle accumulator.
- Add internal provider-tool activity engine telemetry.
- Integrate every current output normalizer: official OpenAI Responses and LiteLLM Responses.
- Add nullable canonical status to provider-tool call payloads.
- Project provider-tool activity into Redis-backed live Events.
- Remove live activity on durable call/result handoff, failed-attempt discard, Stop, and terminal cleanup.
- Add backend unit and integration tests.
- Regenerate OpenAPI and generated public clients if the canonical event schema changes the public contract.

Dependency: PR 2.

### PR 4 — Frontend generic provider-tool lifecycle

- Consume canonical provider-tool call status without provider identity branches.
- Preserve live-to-durable semantic replacement by call ID.
- Improve semantic display labels for known hosted-tool names without provider-specific UI.
- Add reducer/projection tests and Storybook lifecycle states.

Dependency: PR 3.

### PR 5 — Validation

- Add or extend deterministic fixture support for provider-tool lifecycle streams.
- Run the required backend, frontend, and E2E verification matrix.
- Record commands, commit, environment, results, and evidence.
- Fix any implementation defects discovered during validation.
- Compare implementation strictly against design and current specs.

Dependency: PR 4.

### PR 6 — Spec promotion

- Update Conversation, Agent Execution Loop, and Chat Session Resync Living Specs.
- Update related spec versions and verification dates.
- Mark the design implemented after validation passes.
- Run spec review and document affected current behavior.

Dependency: PR 5.

### PR 7 — Cleanup

- Remove this temporary implementation plan.
- Keep the ADR, implemented design, Living Specs, code, and tests as source of truth.

Dependency: PR 6.

## Backend Changes

### Projection contract

Introduce immutable discriminated projection variants for content, reasoning, client-tool call deltas, and provider-tool activity. Conversion to engine events must be exhaustive so a new projection variant fails type checking until handled.

### Activity normalization

Implement a shared accumulator with deterministic behavior:

- first observation emits a snapshot;
- exact duplicate emits nothing;
- later non-null arguments enrich the snapshot;
- terminal state cannot regress to running;
- conflicting terminal states retain the first terminal observation;
- call identity is adapter-normalized and non-empty.

### Adapter integration

Both current normalizers must use the same accumulator. Adapter-specific extraction remains local to the adapter module. Tests must prove that native event classes or wire names do not escape into the common projection, engine event, or live Event payload.

### Live projection

Persist provider-tool activity through `LiveEventStore` with a deterministic Session/call identity. `/live` must restore it through `partial_history.items`. Durable provider call or result publication must precede live removal.

### Attempt cleanup

Extend failed-attempt cleanup to provider-tool live Events. Cleanup must occur before retry state publication and must not remove pending input or PostgreSQL-backed active client tools.

## Frontend Changes

- Keep `ProviderToolCallCard` provider-neutral.
- Derive status solely from canonical payload fields and live/durable provenance.
- Use semantic hosted-tool display labels, not provider names.
- Continue pairing provider call/result by `call_id` across live and durable pages.
- Ensure detached history does not render live activity.

## Validation Matrix

| Behavior | Backend tests | Frontend tests | E2E |
| --- | --- | --- | --- |
| Running observation appears immediately | normalizer + projector | reducer/card | required |
| Completed update reuses one identity | accumulator + projector | reducer | required |
| Multiple calls remain independent | accumulator | reducer | required |
| Duplicate/regressive events do not duplicate or regress | accumulator | reducer | required |
| Retry discards previous activity | executor/projector | retry state reducer | required |
| Stop clears activity | projector/session lifecycle | session state | required |
| `/live` restores running activity | service/live store | resync reducer | required |
| Durable event replaces live activity | publisher/projector | semantic projection | required |
| Provider without progress is not guessed | normalizer | no synthetic card | required fixture assertion |

## Fixture and Prerequisite Requirements

Required CI uses deterministic fixtures and must not depend on live credentials.

Fixture support must be able to:

- emit an adapter-native provider-tool running observation;
- pause before model completion;
- emit terminal provider-tool activity;
- complete with a durable provider-tool output item;
- fail after activity to trigger retry cleanup;
- emit multiple call IDs;
- omit progress and provide only final output.

At least one fixture is required for each current adapter family. If the existing deterministic adapter cannot represent native typed events, add a narrow test adapter or scripted normalizer fixture rather than provider-specific product branches.

Optional live-provider validation may use configured credentials. Missing optional credentials skip the check. Present credentials with mismatched asserted behavior fail the optional run and are recorded separately from required CI.

## Evidence Format

For every validation group record:

- exact command;
- working directory;
- commit SHA;
- environment or fixture name;
- pass, fail, or skip result;
- failure diagnosis and fix commit when applicable;
- DOM assertion or screenshot reference for user-visible E2E states.

## Spec Impact Candidates

- `docs/azents/spec/domain/conversation.md`
  - nullable provider-tool call status;
  - Redis provider-tool live projection;
  - durable/live semantic handoff and failed-attempt cleanup.
- `docs/azents/spec/flow/agent-execution-loop.md`
  - typed projection union;
  - provider-neutral adapter activity normalization;
  - Run phase and client-tool separation.
- `docs/azents/spec/flow/chat-session-resync.md`
  - provider-tool live restoration and durable precedence.

## Rollout and Compatibility

- Existing durable events without provider-tool status remain valid.
- No database migration is planned.
- Providers without progress observations remain final-output-only.
- The feature can be reverted by removing the projection variant and live projector handling without rewriting durable history.
- OpenAPI/generated client changes, if any, must be produced from the backend schema and not edited manually.

## Blockers and External Actions

No product decision or live credential is required. Required CI depends only on deterministic test support.

## Cleanup

After validation and spec promotion, delete this plan in the final stack PR. Do not remove the ADR, implemented design, tests, or promoted Living Specs.
