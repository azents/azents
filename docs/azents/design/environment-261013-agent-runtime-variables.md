---
title: "Agent Runtime Environment Variables Design"
created: 2026-10-13
document_role: primary
document_type: design
snapshot_id: environment-261013
tags: [runtime, agent, security, frontend, api]
---

# Agent Runtime Environment Variables Design

References: [Requirements](../requirements/environment-261013-agent-runtime-variables.md), [decision proposals](../adr/environment-261013-agent-runtime-variables.md).

## Current behavior and bounded change

EnvVar and other active Toolkits contribute environment variables to Runtime shell command execution. Runtime Toolkit collects their mappings before Runner process launch. The additive feature gives an Agent manager an independent environment editor on Agent settings → Runtime. Existing Toolkit creation, editing, credentials, allowlists, order, and removal behavior are unchanged. Session pages and chat Runtime panels do not receive the editor.

## Architecture and ownership

The Agent owns one nullable `encrypted_runtime_environment` document. CredentialCipher encrypts the serialized name/value mapping. Agent deletion owns its lifetime. Runtime stop, restart, Profile changes, and physical reset do not alter Agent settings. Runtime capability removal makes shell reads unavailable while retaining the Agent setting; explicit environment-list replacement is its deletion boundary.

Repositories own completed read/write transactions. Settings writes lock the exact Agent row and validate active lifecycle, Workspace identity, and Owner or Agent-admin authority before merging. Public Agent members can read names without management authority; private Agents conceal their setting from non-managers. No API or Runtime I/O occurs within these transactions. Services project metadata, and routes translate bounded access/validation outcomes.

## API and UI

GET and PUT `/agent-runtime/v1/workspaces/{handle}/agents/{agent_id}/runtime/environment` expose `entries` metadata and `can_manage`. PUT supplies the complete desired list. An entry value is a discriminated `stored` reference or `replace` secret. The server revalidates retained references under the row lock and encrypts the new map. Removing every entry stores null, not an empty secret placeholder. No API returns plaintext.

The existing Agent Runtime settings page alone supplies the environment section. Its container uses generated Public client functions through the Agent tRPC router. Stored names are stable local draft keys; a new row receives a local UUID only. Name/value edits and deletes remain local until Save; Discard restores the redacted query. Saved data replaces the exact query cache and invalidates that Agent's environment query. Validation and pending/error/read-only states keep controls coherent. Four locales remain key-aligned; real Storybook components cover the state/interaction matrix.

## Runtime behavior

Runtime Toolkit uses `_runtime_agent_id`, not the child execution Agent identity. At each command, after current Runtime credential capability admission, it reads current settings in a completed read scope and merges them after active peer Toolkit values. It passes the result only to `start_process`. Existing processes keep their original environment. Newly launched commands see saved/replaced/deleted values without a restart. The next Runtime prompt lists variable names only and warns against echoing values. Interactive Terminal and Runner/container-wide configuration remain unchanged.

The proposed duplicate-name precedence is Agent settings last. Removing an Agent entry does not revoke a retained Toolkit's same-name variable. Settings reads fail closed; there is no cached, empty-map-on-error, dual-write, or legacy migration mode.

## Security and bounded validation

Use existing Fernet key management. Keep replacements in SecretStr models and sanitize HTTP request validation. Accept POSIX variable names up to 64 bytes, at most 50 entries, values up to 4096 UTF-8 bytes, and combined names/values up to 100 KiB. Reject NUL values and duplicate desired names or retained references. Existing validation errors never include value text. Plaintext remains in the command preparation/transport path already authorized for Toolkit credentials, not public read models, configuration digests, events, logs, or lifecycle state.

## Migration, rollout, and recovery

Alembic adds one nullable text column with no backfill. Existing Agents have no new contribution; Toolkit data is untouched. New code requires the migration before serving reads. Downgrading drops this new column and its new settings; it leaves retained Toolkit credentials intact. This is a schema migration for the additional setting, not a migration or deprecation of Toolkit-based variables. No operational apply, merge, or deployment is implied by local verification or PR creation.

## Design Authority

- Design revision: `1`
- This is a technical review draft; proposed mechanisms remain visible rather than falsely recorded as approved.

| ID | Mechanism | Authority or proposal | Classification |
| --- | --- | --- | --- |
| M1 | Agent settings-only environment editor | REQ-1, requester-reviewed UI | required |
| M2 | Encrypted per-Agent persistence and redacted metadata | REQ-1, REQ-3; proposed ADR-D1/ADR-D3 | required |
| M3 | Fresh owning-Agent Runtime Toolkit command injection | REQ-2, existing credential admission | required |
| M4 | Preserve existing Toolkits, exclude Terminal/global injection | REQ-2, REQ-4 | required |
| M5 | Agent setting wins duplicate names | proposed ADR-D2; separate approval not recorded | proposed |
| M6 | Explicit stored/replacement operations and whole-list replacement | proposed ADR-D3 and approved redacted editor | proposed |

## Removal and Replacement

No authoritative implementation, Toolkit, credential, data, or configuration is removed. Runtime command collection is extended, and the existing Agent settings page supplies the new section. Temporary UI requirements scratch files are deleted after integration; static Storybook sample stories remain valid and isolated from real persistence. Absence verification checks that EnvVar Provider/API/form paths are unchanged and that no Session page imports the editor.

## Test Strategy

Primary product E2E: create a Workspace, Agent, managed Runtime and primary Session through existing Public/Admin setup paths; save the Agent environment through generated Public API; launch a deterministic Runtime command that hashes a fake test value; replace and delete it; prove subsequent commands receive the new hash or `ABSENT`. This crosses real server, Worker, Runtime Toolkit, Docker Provider, and Runner boundaries. It uses no real external credentials, no direct product DB writes, and no optional skips.

Existing testenv fixture support suffices: Docker core services, deterministic model proxy, and managed Runtime bootstrap. The proxy adds one bounded scripted environment scenario. It never prints the fake value itself. No live credential/prerequisite snapshot is required. JUnit XML, pytest output and Docker diagnostics provide CI evidence; the required suite owns the new test.

Narrower coverage: PostgreSQL migration/encryption/isolation, permission outcomes, secret retention/rename/delete and rollback; safe HTTP validation and exact Agent scope; UTF-8/POSIX/size/count/NUL checks; repeated Toolkit reads, Runtime-owner identity, duplicate precedence, name-only prompts and fail-closed reads. Storybook owns add/save, duplicate/discard, removal/discard plus empty/loading/error/read-only/saving states and responsive renders. Type/lint/format and locale alignment checks are mandatory.

Local E2E completed successfully. Final CI completion is recorded in the PR, rather than treated as deployment evidence.

## Design Approval

- Mode: Collaborative.
- Decision owner: requester.
- Date: 2026-10-13.
- UI scope: approved real Storybook layout and requested implementation PR.
- Full technical Design revision and exact authority set: not separately approved.
- Proposed mechanisms M5 and M6 are explicit PR review items. This document does not retroactively claim a complete Design approval or set an implementation-complete historical marker while that review remains open.
