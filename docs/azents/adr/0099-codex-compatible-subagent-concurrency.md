---
title: "ADR-0099: Codex-Compatible Subagent Concurrency"
created: 2026-07-09
tags: [architecture, agent, engine]
---

# ADR-0099: Codex-Compatible Subagent Concurrency

## Context

Azents adopted a Codex-first subagent model and completed the first hardening pass for prompt wording, `fork_turns`, parent/child write boundaries, and subagent tree projection. The next phase needs to enable model-visible concurrency semantics before Azents can safely reintroduce Codex-style concurrency-slot prompt text and proactive delegation guidance.

Codex multi-agent v2 exposes a configured maximum concurrent thread count to the model with this wording:

```text
There are {max_concurrency} available concurrency slots, meaning that up to {max_concurrency} agents can be active at once, including you.
```

In Codex, the configured default is `max_concurrent_threads_per_session = 4`. The value includes the root/parent agent, so the effective active subagent capacity is `max_concurrent_threads_per_session - 1`, which is `3` by default. Codex also has a configurable agent nesting depth with default `max_depth = 1`, allowing root-to-child spawning by default while requiring configuration for deeper nesting.

Codex normal `spawn_agent` behavior applies backpressure by failing when the active subagent limit is exhausted. It does not queue normal spawn requests. Separate job-style schedulers may keep work pending and retry later, but that is a scheduler concern rather than the normal collaboration-tool spawn semantic.

## Decision

Implement Azents subagent concurrency and nesting limits with Codex-compatible semantics.

Azents agent settings must expose configurable values equivalent to:

- `max_concurrent_threads_per_session`, default `4`
- `max_depth`, default `1`

`max_concurrent_threads_per_session` counts the parent/root agent. The effective active subagent capacity is therefore `max(max_concurrent_threads_per_session - 1, 0)`. With the default value, a root session can have up to three active subagent turns at once.

`max_depth` limits nested subagent spawning depth. With the default value of `1`, the root agent may spawn direct child subagents, but a child subagent cannot spawn a grandchild unless the setting is raised.

When normal `spawn_agent` would exceed active subagent capacity, it must fail with a clear limit error rather than queueing the task. If Azents later adds a job-style scheduler that keeps pending work and retries when capacity becomes available, that scheduler must be separate from the normal `spawn_agent` semantic.

After these limits are enforced, Azents should reintroduce Codex-style model-facing concurrency-slot prompt text using the configured maximum value, not the current remaining slot count. This keeps prompt text stable across turns and avoids cache churn from runtime occupancy changes.

Azents should also align the related pressure prompt with Codex: subagents should be used for concrete, bounded subtasks that can run independently alongside useful local work, critical-path blocking work should usually stay local, and `wait_agent` should be used sparingly when the parent is actually blocked on child output.

## Consequences

- Azents subagent concurrency becomes predictable and model-visible.
- The default model-visible budget matches Codex: four active agents including the parent, yielding three active subagents.
- Normal spawn backpressure is simple and explicit: fail on capacity exhaustion instead of silently queueing.
- Prompt cache stability is preserved because the prompt includes the configured maximum, not current remaining capacity.
- Nested delegation remains disabled by default beyond direct children, but can be enabled through agent settings.
- Proactive delegation prompt text should remain gated until these limits and clear errors are implemented.
- UI and observability can later surface active capacity, limit errors, and nesting failures, but they should not change the core spawn semantics.
