---
title: "ADR-0006: Adopt Agent-Centric Raw Sessions and Optional Dedicated Sandboxes"
created: 2026-05-03
tags: [architecture, backend, engine, infra]
---

# ADR-0006: Adopt Agent-Centric Raw Sessions and Optional Dedicated Sandboxes

## Context

NoIntern's existing runtime used `ConversationSession` as the conversation unit, broker routing key, sandbox lifecycle owner, and `/home/sandbox` owner at the same time. This tightly coupled Slack/Discord threads, Web chat, per-session sandboxes, EFS subPaths, and the file-api backing store.

To remove EFS and move to S3 checkpointing, sandboxes cannot be created at the high-cardinality conversation/thread level. Slack, Discord, GitHub, and Jira already provide external channel/thread/ticket/issue units for conversations and work, so there is little need to keep a separate shared ConversationSession domain as the internal runtime unit.

## Decision

Adopt the following principles:

1. An Agent has exactly one raw session.
2. A Sandbox is an optional dedicated resource.
3. Agent sandbox policy is either `disabled` or `on_demand`. Always-on execution is treated as a prewarm/keep-warm operational optimization rather than a separate policy.
4. Slack/Discord/GitHub/Jira/Scheduler events are routed to the agent raw session through watches/triggers.
5. Web UI directly accesses the agent raw session.
6. High-cardinality spawned agents default to sandbox disabled.
7. Heavy, stateful, or write-oriented tasks that need a sandbox are delegated to a sandbox-enabled specialist agent.
8. Team sandboxes, per-thread sandboxes, and per-alert sandboxes are not adopted.
9. Dedicated sandbox persistence is implemented with S3 tarball checkpoints, and EFS is removed.
10. Skills are agent-scoped and use both DB snapshots and materialized copies in the sandbox filesystem.

## Consequences

### Positive

- Removes the EFS subPath-based per-session filesystem dependency.
- Avoids exploding sandbox and checkpoint costs when many spawned support/alert agents are created.
- Web, Slack, Discord, GitHub, and Jira events converge on the same raw session model.
- Only coding/personal/specialist agents that need a dedicated sandbox pay S3 checkpoint costs.
- Heavy work can be modeled as task delegation, enabling audit, approval, retry, and priority queue support.

### Negative

- Existing `ConversationSession`-centric broker/runtime/schema must be migrated.
- Watch, event origin, explicit output target, and delegation task become first-class domains.
- File/tool capability guards for sandbox-disabled agents must be enforced strongly.
- S3 checkpoint restore latency and File API UX require separate design.

## Alternatives

### Keep ConversationSession as the runtime unit

Rejected. A single entity simultaneously owns chat room, runtime, and sandbox ownership, making EFS removal and the 1-agent-1-session transition difficult.

### Per-thread/per-alert sandbox

Rejected. On-call and support workloads could create hundreds of sandboxes and tarballs per day.

### Team sandbox

Rejected. Read-heavy work is sufficiently handled by API tools. Work that needs a sandbox tends to be heavy work with resource overuse, isolation, and cleanup risks. Specialist delegation is more predictable.

### S3 object-per-file live sync

Rejected. To support shell writes as a first-class capability, the active canonical filesystem must be the sandbox. S3 is used as a checkpoint/artifact backend.

## Status

Accepted. The detailed design follows `docs/nointern/design/agent-session-sandbox-architecture.md`.
