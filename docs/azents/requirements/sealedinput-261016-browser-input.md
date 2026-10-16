---
title: "Confidential Browser Input Delivery Requirements"
created: 2026-10-16
implemented: 2026-10-16
tags: [browser, runtime, security, agent]
document_role: primary
document_type: requirements
snapshot_id: sealedinput-261016
---

# Confidential Browser Input Delivery Requirements

- Snapshot: `sealedinput-261016`
- Document reference: `sealedinput-261016/REQ`

## Problem

An Agent can be authorized to use credentials provided through its Runtime environment, yet entering those credentials through the current Browser tool requires a literal input string in the tool-call arguments. Reading a value through a visible tool result and repeating it in a Browser call can unnecessarily retain plaintext in normal model context and tool history. A missing supported confidential delivery path can also cause models to refuse an otherwise delegated login task.

## Primary Context

### Primary Actor

A user who provides environment variables to an Agent and delegates browser login to that Agent.

### Primary Scenario

The user provides account values through the existing Agent Runtime environment and asks the Agent to log into a website. The Agent can complete the browser field-input steps using those authorized values without needing to place their plaintext in ordinary tool arguments or model-visible preparation output. The user can inspect the task outcome without exposing the entered plaintext through that delivery path.

## Supporting Scenarios or Effects

- Account identifiers and other user-designated field values can use the same delivery path as passwords.
- Ordinary non-confidential field input continues to use the existing workflow.
- A delivery or input failure reports a useful value-free failure instead of a false success or silent plaintext fallback.

## Goals

- Provide a supported browser-input workflow that avoids unnecessary plaintext propagation through normal model and tool-history surfaces.
- Preserve the user's delegation to the Agent to read and use configured environment values.
- Make the supported workflow discoverable to the Agent so it need not invent plaintext-handling steps or treat the delegated login as categorically forbidden.

## Non-Goals

- Prevent the authorized Agent from reading its environment or exercising its existing shell capabilities.
- Add a password vault, credential broker, separate read permission, new website allowlist policy, or new approval ceremony.
- Guarantee that every model will choose to proceed or that every website will permit a login.
- Hide a submitted credential from the website receiving it, or guarantee that arbitrary authorized subsequent shell/browser operations cannot disclose it.
- Rewrite or retroactively sanitize historical plaintext already captured before this feature.
- Expand this snapshot into confidential delivery for every tool argument, file, shell command, browser dialog, or arbitrary payload.

## Requirements

### REQ-1. Complete delegated Browser field input without literal plaintext arguments

The Agent can use an authorized environment value to fill a concrete Browser input field without including that value as literal plaintext in its ordinary Browser tool-call arguments.

**Acceptance criteria**

- A synthetic login can fill both account and password fields through the new delivery path.
- Normal preparation output and Browser tool arguments contain no plaintext canary value.
- The receiving input field contains the intended value, verified by the controlled test fixture rather than by returning the value to the model.
- The existing concrete Session, current target, observation reference and Browser-enabled authority checks continue to apply.

### REQ-2. Keep the delivery path value-free in routine records

Normal preparation, Browser execution and failure handling do not echo the confidential input into routine Agent-visible output or service diagnostics.

**Acceptance criteria**

- Canary checks cover tool-call/result history and the feature's normal logs, validation errors and execution errors.
- Success reports the action outcome without returning the decrypted value.
- Invalid, unavailable or unreadable input reports a value-free error; it does not fall back to a plaintext Browser call.
- Existing browser observation filtering is preserved. This is a delivery-path guarantee, not a blanket promise against a receiving website echoing the submitted value later.

### REQ-3. Respect existing environment delegation

Configured environment access remains an existing Agent capability. Confidential delivery is an available way to reduce unnecessary plaintext retention, not a restriction on an Agent's delegated authority.

**Acceptance criteria**

- No new environment-read prohibition, vault-only requirement, or separate read grant is introduced.
- Existing environment selection, owner resolution, command-time injection and name-only prompt metadata remain intact.
- Agent guidance distinguishes authorized use of supplied environment values from echoing them into routine transcripts.

### REQ-4. Preserve current Browser behavior and isolation

The new delivery path coexists with ordinary input without changing unrelated browser operations or native state ownership.

**Acceptance criteria**

- Ordinary fill, native input, popups, dialogs, captures and live viewing retain their current contracts.
- A failed delivery does not fill the target or close native tabs, erase profiles, restart Runtime or affect another Session.
- Stale or wrong targets are rejected through the existing Browser authority/reference boundaries.

## Fixed Constraints

- Keep the existing Agent Runtime environment as the supplied credential source; existing precedence and command-time injection behavior remain authoritative.
- Retain the existing Browser capability switch, concrete Session/Run resource authority and Runtime generation checks.
- Implementation requires the requester's explicit instruction after technical design. The requester authorized development of the corrected Design on 2026-10-16. Merge, deployment, live credential tests, operational Runtime restart and profile mutation require separate authorization.

## Open Assumptions

- The initial supported operation is Browser field fill, including text/account and password fields. Browser dialog responses and other tools remain outside this bounded snapshot unless the requester expands the scope.
- The previously supplied public-key/runtime-helper approach is the requester-proposed technical direction to evaluate after Requirements confirmation, not a new restriction on Agent access.

## Confirmation

Confirmed by the requester on 2026-10-16 before ADR decisions and implementation Design began. The confirmed initial scope is Browser field fill for delegated account/password environment values. Environment provisioning authorizes Agent reading and use; this feature reduces routine plaintext propagation and does not introduce a new Agent-read restriction.
