---
title: "OpenAI Responses WebSocket Validation Report — 2026-07-17"
created: 2026-07-17
tags: [backend, engine, llm, openai, oauth, testing, websocket]
---

# OpenAI Responses WebSocket Validation Report — 2026-07-17

## Scope

This report validates implementation commit `95e357c5` against ADR-0150 and the OpenAI Responses WebSocket transport design. Validation covers dependency resolution, formatting, linting, type safety, deterministic backend behavior, worker retry propagation, timeout cleanup, custom-endpoint HTTP compatibility, and the planned product E2E selection where the local environment permits it.

No external provider call was made. No credentials, account headers, provider payloads, response identifiers, model output, or raw WebSocket frames were captured as evidence.

## Environment

- Branch: `feature/openai-responses-websocket-validation`
- Implementation commit: `95e357c5`
- Python: 3.14.6
- OpenAI SDK: 2.45.0
- WebSockets: 15.0.1
- Docker daemon: unavailable in the validation runtime
- External OpenAI and ChatGPT OAuth credentials: not used

## Results

| Area | Command or evidence | Result |
| --- | --- | --- |
| Dependency lock | `uv lock --check` from `python/apps/azents` | Passed |
| Installed dependency versions | `uv pip list` filtered to OpenAI and WebSockets | OpenAI 2.45.0; WebSockets 15.0.1 |
| Backend formatting and lint | `uv run ruff check --fix .` and `uv run ruff format .` | Passed; no remaining changes |
| Backend types | `uv run pyright` | Passed with 0 errors |
| Backend tests | `uv run pytest` | Passed: 1,373 passed, 391 skipped |
| Focused transport and worker regression | OpenAI adapter, watchdog, engine adapter, worker executor, and worker tests | Passed: 132 passed |
| E2E static quality | `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright .` from `testenv/azents/e2e` | Passed |
| Documentation validation | `uv run python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check` | Passed before this report; rerun after report generation |
| Diff integrity | `git diff --check` | Passed before this report; rerun after report generation |

## Deterministic Behavior Verified

The backend suite and focused tests verify the following accepted behavior:

- Eligible official OpenAI and ChatGPT OAuth sampling can select the standard Responses WebSocket transport.
- Custom OpenAI base URLs, including `AZ_OPENAI_BASE_URL` and the SDK-supported `OPENAI_BASE_URL`, remain HTTP-only.
- Stable organization, project, account, and custom routing headers are forwarded to the WebSocket handshake without entering the logical request.
- Explicit `stop` and per-request header requests remain HTTP-only.
- One execution-owned socket is reused serially across healthy sequential responses.
- OpenAI API-key continuation remains strict and resets across socket invalidation or physical transport changes.
- ChatGPT OAuth retains complete input, `store=false`, and no `previous_response_id`.
- Connect, send, receive, protocol, and decode failures invalidate the socket, activate keyed HTTP-only state, and surface a safe transient failure code through the failed-Run boundary.
- Authentication, authorization, quota, provider-availability, User Stop, cancellation, and watchdog timeout paths do not activate sticky HTTP fallback.
- Application connect, parsed-event idle, and absolute-attempt deadlines close abandoned WebSocket work through the existing watchdog cleanup boundary.
- No SDK automatic reconnect or inline WebSocket-to-HTTP replay is enabled.

## Product E2E Selection

The planned local E2E selection included:

- custom-endpoint single-turn chat;
- failed-Run retry recovery;
- client-tool call/result/follow-up persistence;
- REST User Stop;
- model-stream idle, absolute, retry-exhaustion, compaction, and Session-title timeout scenarios.

Pytest collected all selected scenarios, but the session fixture could not create its Testcontainers network because the runtime has no Docker socket. All 12 selected scenarios stopped during environment setup before a product assertion ran. This is an environment prerequisite failure, not an observed product failure.

The existing AIMock fixture sets `AZ_OPENAI_BASE_URL` to a custom HTTP endpoint, so the selected CI E2E remains the intended regression proof that the deployment-default WebSocket setting does not alter custom-endpoint chat behavior. The E2E selection should run in normal CI or another Docker-enabled environment.

## External Validation

Live OpenAI Platform validation was not run because it is optional under ADR-0150 and no provider credential was supplied for this validation phase. The previously retained ChatGPT OAuth probe evidence remains external to the repository and was not rerun or disclosed.

## Privacy Review

The implementation and tests log only bounded operational fields such as provider, model, selected transport, connection reuse, safe failure stage, bounded handshake status, fallback activation, and timeout classification. Tests additionally assert that provider exception details do not enter captured logs. Provider content and identifiers remain outside logs and repository evidence.

## Conclusion

All available deterministic backend, dependency, formatting, linting, type, and static E2E checks passed. The implementation matches the accepted ownership, fallback, retry, timeout, continuation, provider rollout, and privacy policy. Product E2E execution remains pending only because Docker is unavailable in the local validation runtime; normal CI is expected to provide the required container environment.
