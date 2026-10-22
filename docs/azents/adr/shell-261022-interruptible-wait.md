---
title: "Interruptible Shell Waiting Decisions"
created: 2026-10-22
tags: [runtime, tools, wait]
document_role: primary
document_type: adr
snapshot_id: shell-261022
---

# Interruptible Shell Waiting Decisions

## Context

See `shell-261022/REQ`. The requester approved the described cancellable,
non-consuming Runner long-poll proposal and requested implementation.

## ADR-D1. Explicit observation, not unsolicited completion input

Accepted on 2026-10-22. Add an owner-scoped Runner process-observation operation.
It replies on lifecycle change or timeout over the existing operation transport.
Worker races it against mailbox/descendant activity. Cancelling observation never
terminates managed processes. `wait` retains only its timeout argument.

Rejected: periodic process-output polls consume buffers; unsolicited completion
push requires a separate subscription/recovery lifecycle and is unnecessary.

## ADR-D2. Default participation and explicit exclusion

Accepted on 2026-10-22. Execution accepts `fire_and_forget`, false by default.
Excluded commands do not keep observation eligible and do not release waiting.
Shell result-yield windows are capped at 10000 ms; longer waiting is explicit.

## Derived consistency boundaries

Runner owns lifecycle state and a monotonically increasing observation position
within its current generation. Durable tool results are the existing authority for
what a model has been told. Observation returns its position as result metadata;
subsequent waits recover the latest committed position for the same Runtime and
generation. This is not output consumption or an automatic session input source.
Lost/uncommitted observation responses may be observed again rather than discarded.
No new database table, configuration mode, or legacy fallback is introduced.
