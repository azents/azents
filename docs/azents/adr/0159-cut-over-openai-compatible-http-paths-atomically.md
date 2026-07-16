---
title: "ADR-0159: Cut Over OpenAI-Compatible HTTP Paths Atomically"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, oauth, rollout, rollback]
---

# ADR-0159: Cut Over OpenAI-Compatible HTTP Paths Atomically

## Status

Accepted. Implementation has not started.

## Context

The official OpenAI SDK HTTP migration covers OpenAI API-key and ChatGPT OAuth across primary sampling, context compaction, and automatic Session title generation. Routing those six combinations independently would leave temporary production states in which one logical provider uses different request, transport, retry, and error owners depending on the call site.

A runtime fallback from the SDK path to LiteLLM could also submit the same logical model operation through two transports after an ambiguous failure. That would make duplicate generation, tool calls, cost, and failure classification difficult to reason about.

The migration still requires an operational rollback path. A rollback should restore the previously deployed LiteLLM implementation by deploying the preceding code version, without requiring a forward-only data migration or a permanent runtime feature flag.

## Decision

The final routing cutover switches all six OpenAI-compatible HTTP combinations atomically:

- OpenAI API-key sampling, compaction, and Session title generation;
- ChatGPT OAuth sampling, compaction, and Session title generation.

Implementation may be divided into reviewable preparatory changes, but no production routing change is enabled until the complete matrix is ready. After cutover, migrated provider calls have one official-SDK HTTP path with no call-site flag, provider flag, shadow request, or LiteLLM transport fallback.

Deterministic parity tests and bounded live verification for both provider dialects are pre-cutover gates. A failed gate prevents cutover rather than enabling runtime dual routing.

Operational rollback deploys the preceding application version, whose routing still uses the LiteLLM implementation. The migration introduces no required database schema migration and does not rewrite existing native artifacts.

Artifacts produced after cutover use `openai:responses:...` compatibility keys. A rolled-back LiteLLM lowerer rejects those artifacts by exact key equality and uses the durable canonical event fallback established by ADR-0154. It must not fail merely because a transcript contains an opaque artifact from the newer adapter. In-memory SDK client and continuation state is disposable and is not required across deployment rollback.

Rollback compatibility is a required fixture: a transcript produced by the SDK version, including OpenAI-native artifacts and SDK-normalized usage, must be readable by the preceding LiteLLM implementation and lower successfully through canonical fallback. Native-only data that the strict compatibility boundary intentionally omits remains an accepted limitation.

## Consequences

- Production never runs a split OpenAI-compatible transport owner across sampling, compaction, and title generation.
- There is no permanent migration feature flag or ambiguous SDK-to-LiteLLM retry fallback.
- Deployment rollback restores the complete previous implementation rather than partially switching call sites.
- New-version transcripts remain structurally readable after code rollback because durable canonical events and usage schemas remain compatible.
- Rolled-back requests do not replay newer `openai` native artifacts and may omit native-only context, consistent with the strict compatibility-key decision.
- Release preparation must retain the preceding deployable artifact and exercise both forward cutover and backward code-version transcript fixtures.
- Any future database or canonical event schema change must be evaluated separately and cannot rely on this transport-only rollback decision.

## Alternatives Considered

### Cut over by provider or call site behind feature flags

Rejected because it would preserve multiple request and transport owners during production rollout and require temporary routing semantics and cleanup.

### Fall back to LiteLLM at runtime after SDK failure

Rejected because an ambiguous SDK failure may already have reached the provider, making a second transport call unsafe and obscuring migration defects.

### Remove the previous implementation without preserving a deployable rollback version

Rejected because the rollout requires an operational recovery path even though the runtime contains only one active transport implementation.
