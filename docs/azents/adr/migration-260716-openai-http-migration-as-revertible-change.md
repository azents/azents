---
title: "Deliver the OpenAI HTTP Migration as One Revertible Change"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, oauth, rollout, rollback, delivery, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: migration-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0161-deliver-openai-http-migration-as-one-revertible-change.md"
---

# migration-260716/ADR: Deliver the OpenAI HTTP Migration as One Revertible Change

## Status

Accepted. Implementation has not started.

## Context

[over-260716/ADR](./over-260716-over-openai-http-paths-atomically.md) requires one atomic runtime cutover across OpenAI API-key and ChatGPT OAuth sampling, compaction, and automatic Session title generation. It permits preparatory code to land before the final routing change, provided production does not run split routing.

The required operational rollback is stricter: reverting only the migration pull request must restore the complete preceding LiteLLM implementation. A stacked delivery would require identifying and reverting several dependent pull requests, even if only the final one enabled routing.

## Decision

Deliver the complete Phase 1 HTTP migration in one pull request. The pull request contains the approved ADRs and design, direct SDK dependency, generic protocol refactor, OpenAI SDK request/client/stream implementation, both-provider routing cutover at all three call sites, deterministic and E2E fixture support, living spec updates, validation fixes, and design implementation marker.

The pull request introduces no database schema migration, canonical event schema change, artifact rewrite, permanent feature flag, shadow request, or runtime SDK-to-LiteLLM fallback. Reverting that one pull request therefore restores the preceding application code and all six LiteLLM routes without requiring a data rollback.

The pull request may contain multiple reviewable commits, but its commits are not released independently. CI and cutover evidence apply to the complete pull request head.

Rollback compatibility remains subject to [artifact-260716/ADR](./artifact-260716-artifact-compatibility-keys-strict.md) and [over-260716/ADR](./over-260716-over-openai-http-paths-atomically.md): a reverted LiteLLM lowerer rejects newer `openai:responses:...` artifacts by exact compatibility key and reconstructs model input from canonical events. Native-only data omitted by canonical fallback remains an accepted limitation.

## Consequences

- One pull request and one pull-request revert restore the complete preceding transport implementation.
- Review scope is larger than the normally preferred stacked delivery, so commits, module boundaries, and validation evidence must remain clearly organized.
- Partial implementation commits must not be deployed independently.
- The pull request cannot merge until all hermetic checks and required live cutover gates pass.
- A later WebSocket phase remains a separate design and pull request after HTTP validation.

## Alternatives Considered

### Deliver preparatory and cutover work as stacked pull requests

Rejected because reverting only the cutover pull request would leave the generic refactor and unused SDK implementation in the deployed code, contrary to the requested one-PR rollback contract.

### Keep a runtime feature flag for rollback

Rejected because [over-260716/ADR](./over-260716-over-openai-http-paths-atomically.md) selected code-version rollback and one active transport owner rather than permanent dual routing.

## Migration provenance

- Historical source filename: `0161-deliver-openai-http-migration-as-one-revertible-change.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
