---
title: "Runtime Stream Session Naming Cutover Implementation Plan"
created: 2026-09-16
updated: 2026-09-16
tags: [runtime, transport, architecture]
---

# Runtime Stream Session Naming Cutover Implementation Plan

## Authority

- Requirements: `docs/azents/requirements/stream-260916-runtime-session-cutover.md`
- ADR: `docs/azents/adr/stream-260916-runtime-session-cutover.md`
- Design: `docs/azents/design/stream-260916-runtime-session-cutover.md`
- Approved Design revision: `1`
- Approved mechanisms: `M1, M2, M3, M4, M5, M6`
- Design delta: `None`

## Delivery shape

This is one focused independent pull request, not a stacked series. The internal
workstreams below are execution order only; all source, generated, test, and
verification changes land together so the hard protocol cutover is atomic.

## Observable deliverable

The repository uses `RuntimeStreamSession` protocol and reusable transport names,
with regenerated protobuf Python surfaces and no old transport aliases. Runtime Web
public APIs, Gateway policy, HTTP/WebSocket behavior, Owner route persistence, and
one-hop routing remain unchanged. File-specific behavior remains deferred.

## Workstreams and ordering

1. Rename the protobuf source and regenerate Python modules/stubs/gRPC stubs.
2. Rename shared session state, flow-control, Runner client, broker, Owner, relay,
   server, and Runner session-manager surfaces according to the Web adapter boundary.
3. Update Control server composition, Gateway adapters, Runner Control offer wiring,
   Runner dispatcher, tests, exports, and all imports.
4. Verify descriptor identity/fingerprint, absence of removed names, focused behavior,
   static checks, documentation validation, and repository status.

## Removal obligations

- Remove `RuntimeWebSession*` protobuf symbols and old generated module path.
- Remove reusable `runtime_web_*session*` implementation imports and names.
- Remove the old fingerprint constant and compatibility paths.
- Retain Runtime Web product/API, Gateway policy, route repository/table, and
  adapter-local HTTP/WebSocket names.
- Add no file-specific protocol, state, API, storage, or test behavior.

## Validation matrix

- Proto generator output and generated descriptor assertions.
- Shared runtime-control session/flow tests.
- Runner stream client, offer, dispatcher, and loopback HTTP/WebSocket tests.
- Control server, broker, Owner, relay, Gateway, and composition tests.
- Ruff/format, type checking, targeted package pytest, docs/pre-commit checks.
- Repository-wide old-name absence and retained Runtime Web boundary scans.

## Scope and context checkpoints

At completion, record the changed interfaces, generated artifacts, focused test
commands/results, absence evidence, retained Web-specific surfaces, and any CI
blockers. No material design decision may be introduced by implementation.
