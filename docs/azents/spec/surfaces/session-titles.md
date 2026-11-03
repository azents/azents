---
title: "Session titles"
created: 2026-11-04
tags: [wiki]
---

# Session titles

Owns manual naming, deterministic first-input titles, auxiliary model generation and conditional replacement. Naming cannot delay Agent work or overwrite a newer human choice.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Conversations and events](../domain/conversation.md)
- [Model selection and operation snapshots](../models/selection.md)
- [External Channel delivery](../flow/external-channel-delivery.md)

## Manual and automatic naming

Each session may have a user-facing `title`. `PATCH /chat/v1/sessions/{session_id}/title`
sets or clears a manual title after workspace membership validation. The request body uses `{ "title":
string | null }`: non-null titles are trimmed and must be non-empty and at most 200 characters; an
explicit `null` clears the title and title source so automatic title generation may run again. Manual
titles set `title_source = manual` and automatic generation must never overwrite them.

Automatic title generation has two phases. When the first eligible input is promoted into the durable
transcript and the session has no title source, the server stores a deterministic `auto_initial` title
from the beginning of that input. Ordinary Sessions use the first `user_message`. A newly created
External Channel root Session may instead use only the creation-marked human
`authorized_invocation` event; surrounding context, later invocations, Bots, Agent output, and tool
results are ineligible. Its title text is limited to the authorized body and bounded safe attachment
names and media types without reading attachment contents. The worker then immediately schedules
best-effort lightweight model title generation from that exact initial prompt without waiting for the
first run to complete. A NEW title operation compiles local metadata for the same
configured Lightweight candidates, then freezes an independent cursor and
candidate-local retry counter. Captured final `structured_response` support and
its actual request conditions select either the strict one-field Structured
Output contract or title-only plain text. Omitted effort can use a known captured
default for evaluation; actual output-tool shape is validated by the shared
effective-request gate. Strict function schemas remain independent of native
structured output. Invalid structured title output fails the operation rather
than entering an unknown-support compatibility branch. A normalized `quota_or_billing` failure shares Workspace
cooldown and advances to the next candidate; authentication, ordinary rate limiting, timeout,
transport, provider availability, and other operational failures retain the active candidate and its
existing retry policy. Shared instructions preserve request-named products, tools, filenames, and
technical terms and tell the model to ignore platform markup used only to address the Agent without
rewriting the canonical input.

The resulting concise `auto_generated` title only replaces the deterministic title while
`title_source = auto_initial` and `title_generation_event_id` still points at the same initial prompt
event. Manual title updates or clears therefore remain authoritative, while long-running first turns
do not delay automatic title generation. Title generation and any post-commit External Channel title
projection failures must not affect run execution.

The title generation database snapshot and conditional replacement are completed
repository operations. OAuth freshness, model generation, and External Channel
title projection execute only after the relevant repository transaction closes.
Retry checks load a fresh completed ownership snapshot before another model
attempt.

Clients display `title` when present and otherwise fall back to a contextual label such as "Team
primary" or "Session". Concrete session route top bars show this session title while preserving the
Agent avatar/icon affordance, and expose an inline title edit action that calls the manual title update
endpoint. The Web document title mirrors the displayed session title as `{session title} - Azents`.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/services/chat`](../../../../python/apps/azents/src/azents/services/chat)
- [`python/apps/azents/src/azents/worker`](../../../../python/apps/azents/src/azents/worker)
