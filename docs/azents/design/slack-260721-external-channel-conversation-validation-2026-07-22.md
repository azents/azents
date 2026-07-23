---
title: "External Channel Agent Conversation Validation"
created: 2026-07-22
tags: [slack, external-channel, validation, e2e, testenv]
document_role: supporting
document_type: supporting-validation-report
snapshot_id: slack-260721
migration_source: "docs/azents/design/slack-260721-external-channel-conversation-validation-2026-07-22.md"
---

# External Channel Agent Conversation Validation

This report records the PR 13 local validation snapshot for the
`slack-260721` External Channel Agent Conversation implementation.

## Environment

- Branch: `feature/external-channels-13-validation-e2e`
- Base commit: `e2c77a42`
- Platform: Linux 6.8.0 x86_64
- Python: 3.14.6
- uv: 0.11.1
- Node.js: 24.18.0
- pnpm: 11.15.1
- Docker daemon: unavailable; `/var/run/docker.sock` was absent

## Deterministic Provider Infrastructure

PR 13 adds one credential-free Slack provider fake with:

- `auth.test` identity validation and invalid, revoked, rate-limited, and
  unavailable states;
- channel membership, Slack Connect, and unsupported direct-message states;
- cursor-based thread history pages and retryable or terminal failures;
- deterministic permalinks;
- post, update, and delete outcomes including failed, revoked, ambiguous, and
  timeout behavior;
- Socket Mode endpoint creation, real WebSocket handshakes, controllable
  envelopes, disconnect reasons, and acknowledgement traces; and
- sanitized evidence that excludes authorization headers, credential values,
  and Slack message text.

The deployed E2E server and worker use the fake only through explicit
`AZ_TESTENV_SLACK_*` endpoint overrides. Production defaults remain the
official Slack HTTPS and secure WebSocket endpoints. Insecure `ws://` endpoints
are accepted only when both the test API override and the dedicated insecure
WebSocket flag are set.

## Added Journeys

### Deterministic API lane

- create a dedicated HTTP Slack connection and Agent route through the
  generated public client;
- validate redacted credentials, provider identity, transport, and
  capabilities;
- verify exact raw-body callback signing, URL verification, bounded ACK time,
  and duplicate event admission;
- process an unknown participant through membership validation, history
  hydration, permalink resolution, one control-message attempt, and an opaque
  approval request;
- apply the Agent-scoped Allow decision twice and verify one active binding and
  grant;
- process `app_uninstalled` and verify the connection and route become
  terminal;
- create a Socket Mode connection, admit an Events API envelope, observe its
  post-admission ACK, and fence a `link_disabled` connection; and
- assert provider traces never contain the test credentials.

### Web Surface lane

- authenticate through the real Main Web password flow;
- render an active connection at the mobile viewport;
- verify provider identity, transport, route, capability, and redacted
  credential state;
- invoke connection validation from the rendered management surface; and
- assert no credential value appears in the page source.

## Local Results

| Area | Command or selection | Result |
| --- | --- | --- |
| Backend formatting and lint | `uv run ruff check .` and `uv run ruff format --check .` | Passed |
| Backend type checking | `uv run pyright` | Passed |
| Slack focused tests | HTTP, Socket, and event adapter tests | 36 passed |
| Backend collection | `uv run pytest --collect-only -q` | 2,589 collected |
| E2E formatting and lint | `uv run ruff check .` and `uv run ruff format --check .` | Passed |
| E2E type checking | `uv run pyright` | Passed |
| Fake provider contract | HTTP redaction/scenarios and real WebSocket ACK | 3 passed |
| Deterministic lane collection | Required deterministic marker expression | 234 selected of 249 |
| Web Surface collection | Required Web Surface marker expression | 6 selected of 249 |
| TypeScript formatting | `pnpm run format` | Passed |
| TypeScript lint | `pnpm run lint` | Passed |
| TypeScript type checking | `pnpm run typecheck` | Passed |
| TypeScript production build | `pnpm run build` | Passed |

## Docker-Dependent Verification

The focused deployed E2E journey was invoked, but test setup stopped before any
Azents or provider container started because the current agent runtime had no
Docker daemon or Unix socket. This was an environment failure, not a test or
product assertion failure.

The following required commands remain mandatory in stack CI after all fifteen
PRs exist:

```console
cd python/apps/azents
uv run pytest

cd testenv/azents/e2e
uv run pytest -vv -m 'not live_external and not runtime_provider and not web_surface' ./src
uv run pytest -vv -m 'web_surface and not live_external and not runtime_provider' ./src
```

Those runs include the existing migrated PostgreSQL External Channel FK graph
tests and Session lifecycle schema validation. Optional live Slack validation
remains excluded unless protected disposable credentials are explicitly
available.
