---
title: "External Channel File Transfer Validation Report"
created: 2026-07-23
tags: [validation, external-channel, slack, files, admin, e2e]
document_role: supporting
document_type: supporting-validation-report
---

# External Channel File Transfer Validation Report

## Scope and Source of Truth

This report validates the complete implementation stacked above
`plan/channel-file-transfer` against:

- [`files-260723/REQ`](../requirements/files-260723-external-channel-transfer.md)
- [`files-260723/ADR`](../adr/files-260723-external-channel-transfer.md)
- [`files-260723/DESIGN`](files-260723-external-channel-transfer.md)
- the current living specs listed in the implementation plan

The validated implementation includes bounded inbound metadata and locators, directional
Slack capabilities, explicit one-file Runtime download, sequential outbound Runtime
streaming, direct Admin policy management, generated clients, a credential-free Slack
fake, and the deterministic file-transfer E2E journey.

## Environment

- Date: 2026-07-23
- Python: 3.14.6
- Package managers: `uv` and `pnpm`
- Provider substrate: credential-free Slack HTTP fake and deterministic OpenAI Responses
  proxy
- Runtime E2E prerequisite: Docker daemon socket
- Local limitation: the validation runtime had no Docker daemon socket, so the focused
  Runtime-provider E2E failed during Testcontainers network setup before product code or
  test steps ran. The test remains enabled for the required CI Runtime-provider lane.
- Live Slack credentials: not required and not used
- External Channel database setup: public/Admin/provider APIs only; no direct test write

## Command and Result Matrix

| Area | Command | Result |
| --- | --- | --- |
| Backend complete suite | `cd python/apps/azents && uv run pytest -q` | 2,310 passed, 522 skipped |
| Backend static quality | `uv run ruff check --fix .`, `uv run ruff format .`, `uv run pyright` | Passed; 0 Pyright errors |
| Admin API/client generation | `uv run python src/cli/dump_openapi.py`, `make generate`, `pnpm run generate --filter=@azents/admin-client` | Passed; generator-produced output retained |
| Admin Python client | `cd python/libs/azents-admin-client && uv run pytest -q` | 151 passed |
| Slack fake and model proxy | `uv run pytest -q src/tests/test_slack_provider_fake.py src/tests/test_external_channel_file_proxy.py src/tests/test_external_channel_progress_proxy.py` | 20 passed |
| E2E static quality | E2E Ruff, format, Pyright, and External Channel collection | Passed; 0 Pyright errors; 6 External Channel tests collected |
| Focused Runtime E2E | `uv run pytest -vv -s src/tests/azents/public/test_external_channels.py::test_external_channel_file_transfer_journey` | Environment-blocked before setup: Docker socket absent |
| TypeScript | `pnpm run format`, `pnpm run lint`, `pnpm run typecheck`, `pnpm run build --filter=@azents/admin-web` | Passed sequentially |
| Repository hooks | `uv run pre-commit run` and commit hooks | Passed |
| Diff hygiene | `git diff --check` and phase scope comparison | Passed |

## Deterministic Provider and E2E Evidence

The Slack fake contract verifies:

- `files.info` returns bounded metadata and a private URL without retaining the URL,
  filename, credential, or body in evidence;
- authenticated private download returns configured bytes and records only provider file
  identity and operation counts;
- one upload URL is acquired per file, streamed bodies are retained only as byte counts,
  and completion records ordered file IDs, aggregate bytes, thread identity, and only a
  boolean for text presence;
- configurable missing, rejected, missing-scope, size-mismatch, and ambiguous-completion
  outcomes remain deterministic; and
- evidence never contains bot tokens, signing secrets, provider URLs, filenames, message
  content, or file bodies.

The primary E2E test is collected in the `runtime_provider` lane and performs the
following supported-path journey:

1. configure two direct-upload Slack file metadata entries and private bodies;
2. admit a signed event through `POST /external-channel/v1/slack/events`;
3. create and authorize the binding through public APIs;
4. confirm both bounded locators and the download, Runtime processing, and Channel action
   tools are model-visible;
5. download only the selected file to `/workspace/agent/external-input.txt`;
6. create two deterministic Runtime outputs through `exec_command`;
7. publish one `finish` Channel action containing text and both absolute Runtime paths;
8. verify one completion targets the original channel/root thread with two ordered files,
   36 aggregate bytes, and a non-empty initial comment; and
9. verify provider and Tool history evidence remains sanitized.

CI execution of this collected Runtime-provider test is the remaining final environment
gate.

## Requirement Evidence

| Requirement | Implementation evidence | Validation status |
| --- | --- | --- |
| `files-260723/REQ-1` Discoverable inbound attachments | HTTP, Socket, hydration, renderer, replay, compaction, token-accounting, and bounded metadata/locator tests | Satisfied |
| `files-260723/REQ-2` Explicit single-file materialization | `download_external_file`, provider metadata/download adapter, Runtime destination/overwrite handling, selected-file E2E sequence | Satisfied; CI runs primary Runtime journey |
| `files-260723/REQ-3` Binding-scoped attachment access | Versioned binding locator, Agent/Session/binding/connection ownership checks, lifecycle and authorization tests | Satisfied |
| `files-260723/REQ-4` Fail-closed Slack file scope | Direct-upload classification, unsupported-mode reasons, directional scope capabilities, provider-authoritative failure mapping | Satisfied |
| `files-260723/REQ-5` Configurable transfer limits | Typed direct System Setting, 25/25/100 MiB defaults, hard bounds, aggregate invariant, declared/actual/stat/stream enforcement, Admin optimistic API/UI | Satisfied |
| `files-260723/REQ-6` File attachments in explicit Channel replies | Existing `channel_action`, required text, preflight manifests, ordered sequential streaming, one completion, original-thread evidence, one delivery outcome | Satisfied; CI runs primary Runtime journey |
| `files-260723/REQ-7` Provider-neutral Agent contract | Opaque inbound locator, Runtime paths on existing action, provider credentials/URLs outside Tool contracts, Slack isolated behind provider adapter | Satisfied |

## ADR and Design Conformance

| Decision or boundary | Observed implementation |
| --- | --- |
| Directional Slack capabilities | `download_files` and `upload_files` derive independently from provider scopes; text remains available independently. |
| Provider-authoritative inbound access | The binding-scoped locator resolves to `files.info` and authenticated download at invocation time; no message-local byte cache is trusted. |
| Direct outbound streaming | Runtime files are statted before commit and read in 1 MiB chunks directly into sequential provider uploads without Exchange or private staging. |
| One explicit publication action | Optional `files` extends `channel_action`; no upload-only action exists and text is required for file-bearing publication. |
| Provider-neutral direct System Setting | `external_channel_files` has no secrets, activates directly with optimistic versioning and audit, and has no candidate/health workflow. |
| No durable transferred bytes | Revisions/actions/deliveries retain bounded metadata/manifests only; no attachment table, Exchange object, Artifact, or ModelFile is created by the transfer. |
| One-attempt delivery | Confirmed rejection is failed; upload/completion transport ambiguity is unknown; no automatic replay is introduced. |

No implementation behavior was found to contradict the accepted ADR or approved Design.

## Failures Found and Corrections Applied

Validation and independent review found the following non-blocking gaps, all corrected in
the implementation stack before this report:

1. Slack completion evidence did not prove that text accompanied the files. The fake now
   records only `has_initial_comment`, and fake/E2E assertions require it without retaining
   message content.
2. The Admin plan required whole-MiB input while the UI admitted fractional MiB and rounded
   to bytes. Inputs now reject decimals and convert exact integer MiB values.
3. Fake failure scenarios existed without complete contract coverage. Focused tests now
   cover inbound missing, rejected, and missing-scope responses in addition to upload size
   mismatch and ambiguous completion.
4. The optimistic PATCH route returned a stable 409 but did not publish it in OpenAPI. A
   typed 409 envelope is now generated into both Admin clients, with direct aggregate/range
   route-schema coverage.
5. The Admin card did not explicitly label dirty state. It now shows `Unsaved changes`
   while retaining the draft on failure.

## Implementation Versus Current Living Specs

The code is internally consistent, but the living specs predate this feature and require
promotion in the next PR.

| Living spec | Current gap | Required promotion |
| --- | --- | --- |
| `spec/domain/external-channel.md` | No file metadata, locator, capability, manifest, or transfer ownership contract | Add bounded file records, directional capabilities, opaque locator scope, and no-byte persistence invariant |
| `spec/flow/external-channel-provider-ingress.md` | No Slack `files[]` projection/classification or provider-file redaction rules | Add identical HTTP/Socket/hydration projection, supported modes, truncation, and metadata-only context |
| `spec/flow/external-channel-delivery.md` | `channel_action` is text/task-only and lacks file preflight/stream/completion outcomes | Add optional Runtime files, required text, commit-before-call manifest, sequential uploads, one completion, and ambiguity mapping |
| `spec/flow/external-channel-lifecycle.md` | File locator/publication fences are implicit rather than stated | Add immediate failure after binding/connection/Session/Agent terminal transitions and no transferred-byte cleanup participant |
| `spec/flow/file-exchange-storage.md` | Does not distinguish External Channel transfer from Exchange/Artifact/ModelFile storage | Add the metadata-only, explicit Runtime transfer boundary and direct provider streaming non-storage contract |
| `spec/flow/agent-execution-loop.md` | Does not describe the External Channel download Tool or file-bearing Channel action Runtime dependency | Add run-scoped Runtime write/read behavior and provider-neutral Tool exposure |
| `spec/domain/system-settings.md` | Does not include `external_channel_files`, its direct activation, limits, or Admin surface | Add section schema, defaults/bounds, optimistic Admin API, audit, and direct-save UI |

No current-spec statement requires code rollback. These are additive documentation gaps
owned by the spec-promotion PR.

## Accepted Risks and External Boundaries

- Mandatory CI remains credential-free. Live Slack workspace policy, file retention, or
  file-size rejection is provider-controlled and may differ from the deterministic fake.
- Existing Slack Apps require the corresponding `files:read` and/or `files:write` scope
  and reinstallation before validation grants each capability.
- Provider URL trust follows authenticated Slack API responses and the explicit local
  test origin. URLs never enter Agent-visible or durable transfer state.
- Inbound Runtime writes remain whole-buffered by the existing Runner write contract but
  are bounded by the configured hard limit. Outbound reads are chunked.
- The local validation environment cannot supply Docker; therefore the CI
  Runtime-provider lane is a required final gate rather than an optional signal.

## Readiness

The implementation, generated contracts, Admin surface, provider fake, unit/service
coverage, and complete backend suite are ready for living-spec promotion. The stacked
spec and cleanup PRs may be prepared before CI monitoring as required by the delivery
workflow. Final implementation verification and the implemented snapshot date remain
gated on a passing CI Runtime-provider E2E result across the complete stack.
