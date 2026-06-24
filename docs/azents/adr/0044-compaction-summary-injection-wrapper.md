---
title: "ADR-0044: Use Handoff Resume Wrapper When Injecting Compaction Summary"
created: 2026-05-31
tags: [architecture, backend, engine]
---

# ADR-0044: Use Handoff Resume Wrapper When Injecting Compaction Summary

## Status

Accepted.

## Context

ADR-0043 decided to generate compaction summaries as Codex-like handoff checkpoints. However, even if the summary generation prompt improves, if the generated summary is injected into the next model input as a raw user message, the next agent can interpret it as ordinary conversation content or as a message to confirm.

Especially when the next user input after compaction is short or test-like, the agent may respond as if it manually verified the summary and end the turn instead of continuing the `Pending Work` in the checkpoint.

Codex's compaction implementation adds a separate prefix before the summary, explicitly saying that another language model started the work, and the current model should continue from the summary while avoiding duplication. Azents needs a wrapper with the same meaning when reinjecting the generated checkpoint into the model.

## Decision

When lowering a `compaction_summary` canonical event into LiteLLM Responses input, do not use raw summary content directly as user message content.

Instead, wrap the summary with an English model-visible wrapper with this meaning, then inject it as a user message:

- another agent started this task and produced this summary
- the current agent also has access to current tool and repository state
- use the summary to build on work already done
- avoid duplicating work
- use the summary to assist the current analysis

The summary body is placed inside a `<summary>` block to provide a clear boundary.

This wrapper is model-visible internal context, not product UI text. Therefore it is not subject to locale message translation and remains English.

## Consequences

- Compaction summary is more likely to be interpreted as a handoff checkpoint rather than a bare user message.
- The next agent can continue based on the summary without duplicating already completed work.
- Because summary may be stale, actual file, branch, PR, CI, and tool state must be re-verified against current state before acting.
- Wrapper text affects model behavior, so regression tests pin lowerer output.
