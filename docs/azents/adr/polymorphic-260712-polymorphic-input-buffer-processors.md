---
title: "Use Polymorphic Input Buffer Processors"
created: 2026-07-12
tags: [architecture, backend, engine, python, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: polymorphic-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0136-use-polymorphic-input-buffer-processors.md"
---

# polymorphic-260712/ADR: Use Polymorphic Input Buffer Processors

## Context

The current `InputBufferService` combines FIFO selection, profile-segment construction, buffer-kind branching, action-subtype branching, domain side effects, event construction, run association, deletion, and turn-boundary behavior in one service. The new design processes exactly one FIFO item at a time, and each remaining buffer kind now has an explicit preparation contract.

Those contracts differ enough to require separate implementations but share one queue lifecycle and one structured turn-effect model. Keeping a single growing conditional would make the sequential redesign easier to implement initially but harder to test and extend safely.

## Decision

Implement input-buffer preparation through polymorphic processors behind a shared orchestration layer.

The orchestration layer owns only cross-kind mechanics:

- claim the next durable FIFO buffer item;
- select the processor by buffer kind and, for `action_message`, by the typed action discriminator;
- provide the session and execution preparation context;
- invoke exactly one processor at a time;
- fold the returned turn effect according to [fold-260712/ADR](./fold-260712-fold-turn-eligibility-with-failure-veto.md);
- continue until the durable queue is empty;
- coordinate common retry, unexpected-exception, observability, and empty-boundary behavior.

Each concrete processor owns its type-specific behavior:

- payload validation and typed decoding;
- model and effort resolution when the type applies inference overrides;
- domain-state mutations;
- durable semantic event construction and append behavior;
- model-file or attachment preparation required by its message type;
- handled failure classification;
- buffer consumption semantics;
- final structured preparation outcome.

Use separate concrete processors for:

- `user_message`;
- `action_message.goal`;
- `action_message.skill`;
- `action_message.create_git_worktree`;
- `goal_continuation`;
- `agent_message`.

`edited_user_message` and `background_completion` receive no processors because those kinds are removed by [handle-260712/ADR](./handle-260712-handle-message-edits-as-transactional-preparation.md) and [background-260712/ADR](./background-260712-background-completion-input.md).

The shared processor contract returns a typed preparation outcome containing at least the success/failure classification and `TurnEffect` (`eligible`, `neutral`, or `failed`). Handled failures are returned as values after their durable failure result commits. Unexpected technical failures raise, roll back the current atomic work where applicable, and leave the buffer available for recovery.

Do not make SessionRunner or the orchestrator branch on payload fields after dispatch. Adding an action subtype requires a new processor and exhaustive registration, not another conditional inside the queue-drain loop.

The design may use Python Protocols or an equivalent explicit interface, but dependency construction remains normal constructor injection. The processor registry is an application composition concern and must remain exhaustive and testable rather than relying on hidden module-global registration.

## Rejected Alternatives

### Keep one service with a kind/action match statement

This centralizes code but combines unrelated domain dependencies and failure semantics in the queue lifecycle. Every new type changes the same high-risk service.

### Put FIFO and turn folding inside each processor

Processors would duplicate queue mechanics and could apply inconsistent ordering or eligibility rules.

### Use dynamic global plugin registration

The supported input kinds are a closed product contract. Hidden import-time registration weakens dependency injection and exhaustive type checking without a current need for third-party buffer processors.

## Consequences

- Queue mechanics and message semantics can be tested independently.
- Each processor has a smaller dependency surface and focused unit tests.
- Action subtypes become first-class preparation implementations even though they share one storage kind.
- Worktree preparation can retain its durable multi-step action-execution state machine behind the same final processor outcome contract.
- The orchestration layer becomes the single authority for FIFO draining and turn-effect folding.
- Processor registration and closed-union exhaustiveness require dedicated tests.
- The final feature design must define the exact processor context, outcome ADT, transaction helper, and worktree long-running operation interface.

## References

- [drain-260712/ADR: Drain Input Buffers Sequentially Before Turn Start](./drain-260712-drain-input-buffers-before-turn-start.md)
- [handle-260712/ADR: Handle Message Edits as Transactional Preparation](./handle-260712-handle-message-edits-as-transactional-preparation.md)
- [action-260712/ADR: Keep Action Messages Buffer-Only](./action-260712-action-messages-buffer-only.md)
- [fold-260712/ADR: Fold Turn Eligibility with Failure Veto](./fold-260712-fold-turn-eligibility-with-failure-veto.md)
- [background-260712/ADR: Remove Deprecated Background Completion Input](./background-260712-background-completion-input.md)
- [directly-260712/ADR: Directly Promote Continuation and Agent Messages](./directly-260712-directly-promote-continuation-and-messages.md)

## Migration provenance

- Historical source filename: `0136-use-polymorphic-input-buffer-processors.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
