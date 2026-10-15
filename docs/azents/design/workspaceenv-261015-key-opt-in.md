---
title: "Workspace Environment Key Opt-In Design"
created: 2026-10-15
document_role: primary
document_type: design
snapshot_id: workspaceenv-261015
tags: [workspace, runtime, security, frontend, api, testenv]
---

# Workspace Environment Key Opt-In Design

References: [Requirements](../requirements/workspaceenv-261015-key-opt-in.md), [decisions](../adr/workspaceenv-261015-key-opt-in.md).

## Mechanisms and boundaries

`workspace_environment_variables` owns immutable IDs, Workspace FK, unique names and Fernet-encrypted values. `agent_workspace_environment_selections` owns only explicit Agent/variable ID pairs with cascading FKs. Migration creates empty tables; no existing Agent is opted in. New/recreated/renamed identities cannot reuse old selection IDs. Existing Agent-local encryption is unchanged.

Repository catalog replacement authorizes Owner/Manager, locks Workspace, resolves exact prior IDs, validates retained references and desired names/values, deletes omitted/renamed identities and inserts replacements. Same-name edits preserve IDs. Selection writes acquire Workspace then Agent locks, recheck lifecycle/Workspace/Owner-or-admin authority, reject missing/foreign IDs, and replace the set atomically. Reads use database read-only scopes. No external I/O occurs inside write transactions.

`AgentRuntimeEnvironmentRepository.read_values` uses one outer-join statement scoped to the managed active Runtime owner and its exact Workspace. Selected shared secrets are decrypted/validated, then Agent-local values override them. Existing Runtime Toolkit capability admission and peer collection are retained, so final precedence is Toolkit → Workspace → Agent. Fresh reads occur per command; failure prevents command launch. Prompts list only effective names. Values are not returned through public management responses, events, logs or validation details.

## Interfaces and UI

Workspace v1 GET/PUT `/workspaces/{handle}/environment` expose shared metadata and complete desired-list edits with exact nullable ID, desired name and existing stored/replace value union. GET/PUT `/workspaces/{handle}/agents/{agent_id}/environment-selection` expose current names, selected IDs, overridden names and management authority. PUT takes the complete selected-ID set; none means none, not inherit all. Request validation uses the existing secret-safe Runtime route. Services delegate completed repository operations; generated clients own frontend wire contracts.

Workspace settings links to a dedicated environment page and reuses the existing editor with explicit shared-scope copy. Agent settings → Runtime alone composes the local editor and new selection component. Selection state is container-owned and rendered from props; checkbox choices remain local until Save. Query invalidation refreshes metadata after Workspace/local edits. Stale deleted selections fail clearly and can be discarded/reloaded. Stored values are never revealed. Four locales and mobile stacking follow the existing product theme.

## Migration and failure recovery

Upgrade creates two empty tables; downgrade removes selection rows and shared variables without changing Agent-local values. Use ordinary schema rollout before serving new reads. No platform versions, history, fallback, cache, Provider document or restart mechanism. Editing errors roll back atomically. Already-prepared/running process environments are not revoked. Shared variables and selections survive ordinary Runtime lifecycle actions and are deleted with their owning Agent/Workspace or explicit variable removal.

## Design Authority

Design revision: `1`. The requester delegated planning and implementation through PR; implementation choices remain visible for PR review.

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Shared encrypted catalog; metadata-only read | REQ-1, ADR-D1 | decided |
| M2 | Default-empty per-Agent key selection and Agent settings-only editor | REQ-2, ADR-D4 | required |
| M3 | Delete/rename/recreate invalidates identity and stale opt-in | REQ-4, ADR-D1/D2 | decided |
| M4 | Single-snapshot Runtime owner resolution, shared below local | REQ-3, ADR-D3 | decided |
| M5 | Owner/Manager shared edits, Owner/admin selection | REQ-1/2, ADR-D4 | decided |
| M6 | Existing validation/crypto/secret-safe errors and independent source bounds | REQ-1/5, existing Agent environment spec, ADR-D3 | existing |

## Removal and Replacement

No Toolkit, credential or public interface is removed. Replace the narrow Agent environment read query with joined source composition and extend the editor's scope copy without changing local behavior. Existing editor stories remain; new selection/catalog stories add meaningful coverage. Delete the temporary implementation requirement note after consolidation. Check that no Session route imports the editor and no previous Toolkit data path is changed.

## Test Strategy

Primary product E2E extends the existing credential-free environment journey across actual Public API, Worker, Docker Provider, Runtime Toolkit and Runner. Verify: common catalog default none; explicit key selected; shared value update applies next command; deselect removes contribution; deletion plus same-name recreation stays unselected. Existing local save/replace/delete checks remain. Fake values are compared as hashes; no real credentials/prerequisite snapshot is needed. Use existing product setup helpers, no direct DB writes. CI required E2E suite executes the updated test with JUnit/log artifacts.

Narrower PostgreSQL tests verify encryption, isolation, Manager catalog permission versus Agent permission, stale IDs, duplicate/foreign references, rename/delete cascade, local override and removal revealing selected shared values. HTTP tests verify exact Workspace/Agent scope and sanitized invalid secret bodies. Existing Runtime/Agent environment tests remain regression checks. Storybook covers default-none, empty/loading/error/read-only, selected/overridden, stale errors and select/save/discard; actual desktop/mobile renders use product theme/fonts, Korean locale, native DPR1 capture. Frontend tests, type/lint/format/build, backend Ruff/ty/pytest and migration chain checks are mandatory.

## Design Approval

The requester additionally required delete buttons to align with the input, not its helper text, on 2026-10-15. Both shared/local editors now place labels, controls, descriptions and errors in separate grid tracks; delete buttons align to the control track. Native desktop/mobile browser geometry showed zero center-offset and a Storybook assertion protects the alignment.

### Feasibility and approval record

Feasible: new tables avoid historical ORM-column fixture drift; existing credential cipher, Agent authority, Runtime owner ID, secret-safe route and editor are reusable. Local PostgreSQL integration and actual shell E2E passed; current frontend type/lint and visual interaction checks passed. Risks: full-list last-writer semantics, Workspace manager updates affecting opted-in Agents, and process-preparation snapshot behavior are explicit.

Mode: autonomous execution within the requester's 2026-10-15 bounded delegation. Main agent owns integration and final choices; an independent read-only opinion recommended immutable identities and warned against name-only consent. UI and technical revision `1`, authority set `M1–M6`, are delivered for PR review under that delegation. This does not claim a separate requester review or an independent complete-Design approval that did not occur. No merge/deployment authority is inferred.
