---
title: "ADR-0057: Adopt Event / Native Event Terminology"
created: 2026-06-13
tags: [architecture, backend, engine]
---
# ADR-0057: Adopt Event / Native Event Terminology

## Status

Accepted.

## Context

The durable event model of Azents runtime transcript is not a "canonical event" with a separate opposite concept. It is the normal event inside the system. Keeping the `canonical` prefix or package to distinguish it blurs the boundary between durable transcript event and lower target event.

On the other hand, an event lowered into model/provider adapter is no longer an Azents event, but a target-native event. Provider- or adapter-specific native representations such as LiteLLM Responses, OpenAI Responses, and Claude Messages should each have explicit names.

## Decision

- Durable transcript model is called `Event`.
- Event kind enum is called `EventKind`.
- Durable event package uses `azents.engine.events`.
- Generic lower target boundary is called `NativeEvent`.
- LiteLLM Responses stream wrapper is called `LiteLLMEvent`.
- Do not keep `canonical` package, type alias, or compatibility wrapper.

## Consequences

Runtime, repository, broker, API schema, generated clients, web chat type names, and living spec use the new terminology. Historical ADR/design documents may still contain previous wording as decision history, but current implementation and spec surfaces use `Event`, `NativeEvent`, and adapter-specific native event names.
