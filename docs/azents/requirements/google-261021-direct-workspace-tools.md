---
title: "Direct Google Workspace Tools Migration Requirements"
created: 2026-10-21
updated: 2026-10-21
document_role: primary
document_type: requirements
snapshot_id: google-261021
tags: [google, toolkit, oauth, migration, security]
---

# Direct Google Workspace Tools Migration Requirements

- Snapshot: `google-261021`
- Document reference: `google-261021/REQ`
- Confirmed by the requester on 2026-10-21 before ADR decisions.
- The requester subsequently confirmed actual OAuth grants as the action-permission
  authority on the same date; the updated requirements below incorporate that
  product change before technical decisions are accepted.
- The requester also confirmed omission of Google-specific prompt-content
  screening from the direct integration on 2026-10-21.
- Drive uses whole-Drive access by default, with optional app-authorized-file
  access and a file-selection entry point. Implementation and deployment remain
  outside this design approval.

## Problem

The Google integration currently depends on official remote MCP services and their
availability conditions. Its admitted actions are narrower than the requested
Gmail, Calendar, and Drive feature set. Managers need sufficient task coverage with
truthful OAuth permissions, while existing connections need a defined transition
that preserves identity, ownership, and actual Google authorization.

## Primary System Outcome

Transition the built-in Google integration from official remote MCP execution to
Azents-provided Gmail, Calendar, and Drive tools. New and existing connections use
independent service controls and actual Google-grant-derived capabilities, without
changing the connected account, manufacturing consent, or requiring per-operation
approval. Azents does not maintain a second manager-selected action-permission
layer inside an enabled service.

## Supporting Scenarios or Effects

- A connection manager enables required services, chooses understandable OAuth
  request bundles, and inspects actions permitted by actual Google authorization.
- An existing connection remains associated with its current Workspace, owning
  Agent or User, and allowed consuming Agents through the transition.
- An Agent performs an authorized task using the connected account, not the chat
  participant's account or a model-supplied account selector.
- A manager disables a service without repeating OAuth, or changes requested
  Google access through connection/reconnection management.

## Goals

- Provide the Gmail, Calendar, and Drive feature breadth represented by the public
  community reference at commit `484f64b5a43ddfed0d1e214f7e1038076d904c5b`.
- Preserve applicable existing capabilities and connection authority.
- Make each service independently controllable, with understandable Google access
  requests and truthful actual-grant status.
- Derive supported actions from actual Google grants rather than maintaining a
  duplicate selected-action permission list.
- Complete the Google-specific remote MCP replacement without introducing a
  permanent alternate execution mode.

## Non-Goals

- Operating a separate Workspace MCP server or adding a Google MCP fallback mode.
- Generalizing or removing generic MCP support used by other integrations.
- Adding per-operation confirmation dialogs, approval requests, approval queues,
  approval expiry, or approval-based execution resumption.
- Adding other Workspace services or dedicated Docs, Sheets, or Slides structural
  editing. Drive format import and export remain in scope.
- Adding general Gmail permanent deletion, delegation, account-wide forwarding
  configuration, or alias administration.
- Adding Calendar ACL, calendar ownership transfer, or calendar deletion features.
- Automatically revoking Google consent or undoing remote changes when a service
  is disabled or the local connection is disconnected.
- Treating deterministic provider fixtures as live Google interoperability evidence.
- Adding a second action-permission list, per-group ceiling, or old-effect
  allowlist that intersects actual Google grants within an enabled service.
- Carrying forward the Google-specific prompt-injection regex scanner or its
  blanket uninspectable-binary rejection, or adding Model Armor/content-scanning
  services for this direct integration.

## Requirements

### REQ-1. Built-in direct service capabilities

Azents provides Google operations without depending on an official Google MCP
endpoint or its Preview admission.

**Acceptance criteria**

- Authorized Gmail, Calendar, and Drive operations are available through the
  built-in Google integration without a separately operated Workspace MCP server.
- Google API enablement, OAuth configuration, account restrictions, and Google
  verification requirements remain accurately described.
- The generic MCP integration, Google Analytics integration, and unrelated Toolkit
  providers retain their existing behavior.

### REQ-2. Independent services and Google-grant-derived tools

Managers control Gmail, Calendar, and Drive independently. Request bundles
configure Google OAuth requests; actual returned grants determine available
supported actions inside each enabled service.

**Acceptance criteria**

- Turning one service off leaves other service selections and the connection intact.
- Enabling a service admits only supported tools with sufficient actual Google
  grants; it does not manufacture missing permissions.
- All supported actions permitted by sufficient actual grants are eligible for
  exposure in an enabled service, subject to current account, Agent, and resource
  access. A second Azents action selection does not narrow that set.
- Requested scopes and request-bundle selections are not proof of actual consent,
  nor are they a second post-consent action allowlist.
- Tools requiring different scopes are filtered individually after partial consent;
  no service or group is assumed fully usable from a successful OAuth return.
- Disabling every service leaves a manageable inactive saved connection, with no
  Google tool execution; it is not represented as usable capability.
- Action names describe concrete work. Selectively applied caution labels describe
  consequential effects and are not an advanced-feature tier, a Google scope
  classification, or an execution-approval mechanism.
- New connections do not request every service or write scope automatically.
  Whole-Drive is the initial file boundary, not consent to write; requests still
  reflect the manager's chosen Google access bundles.

### REQ-3. Gmail feature coverage and OAuth scope semantics

Gmail supports message work, drafts, mailbox organization, sending, and filters
according to sufficient actual Google grants.

**Acceptance criteria**

- Read operations cover message and thread search/retrieval, batch retrieval,
  attachments, labels, draft listing/retrieval, and filter retrieval.
- Draft management covers new, reply, and forward drafts. Draft update/deletion is
  an explicit target capability, not a claim about the previous implementation.
- Mailbox organization covers label definition management, message/thread labeling,
  read state, archive, trash/restore, spam state, and batch changes.
- Sending covers new messages, replies, forwards, and explicit saved-draft sending
  when actual Google authorization suffices for the relevant API and prerequisites.
- Filters cover creation, deletion, replacement-based modification, and application
  of supported label effects to existing matching messages.
- External filter-forwarding operations use actual filter-setting scopes and
  Google's verified-target/resource conditions, without an extra Azents forwarding
  permission. Their future external effect is clearly explained.
- Existing-mail application requires actual mailbox-modification scopes as well as
  any needed filter access. Future-mail automation is distinguished from current-mail
  modification, and partial filter replacement/application is not reported as
  complete success.
- `gmail.compose` and `gmail.modify` may admit supported sending tools as well as
  draft work. Request bundles must not promise drafts-only or organize-only
  execution where Google grants include sending.
- Reply, forward, attachment reuse, and related account reads require applicable
  actual Google read scopes; `gmail.send` alone does not permit mailbox reading.
- General message permanent deletion bypassing Trash is unavailable.

### REQ-4. Calendar feature coverage and OAuth boundaries

Calendar supports event work, availability, status events, and secondary calendar
creation according to actual Google scopes and account/resource support.

**Acceptance criteria**

- Read operations cover calendar listing and event search/retrieval, including
  recurring and supported special-event types.
- Availability-only permission returns busy intervals and derived time suggestions
  without exposing event descriptions, attendee details, or other event content.
- Event editing covers create, update, delete, RSVP, attendee changes, supported
  recurring-event operations, and meeting information.
- Out-of-office and focus-time operations are available when actual event scopes
  and account support suffice; automatic invitation decline and status effects
  are explained rather than gated by an extra Azents permission.
- Secondary calendar creation is offered without representing it as inherently
  advanced or applying a blanket caution label.
- Unsupported account features, missing resource permission, and missing OAuth
  permission are not conflated.
- Calendar sharing, deletion, and ownership transfer are not introduced.

### REQ-5. Drive feature coverage and file boundaries

Drive supports file reading, authoring, conversion, and access management without
conflating actual OAuth operation scopes with the set of accessible files.

**Acceptance criteria**

- Reading covers search/listing, metadata, content, download/export, existing link
  retrieval, permission inspection, and public-access inspection.
- Authoring covers file/folder creation, copy, import into Google Docs/Sheets/Slides
  formats, supported content replacement, rename/description, move, starring, and
  trash/restore.
- Editing and sharing have explicit tool contracts but no extra manager-selected
  Azents permission split. A sufficient `drive` or `drive.file` grant can admit
  supported sharing and ownership tools for eligible files.
- User/group sharing, public/domain sharing and access-policy changes, and ownership
  transfer obey Google's scopes and resource capabilities. Consequential effects
  receive appropriate caution information.
- Existing-link retrieval does not create public access.
- Whole-Drive reading plus app-authorized-file writing is not represented as
  whole-Drive writing. A known file ID or URL does not establish app authorization.
- Shortcut targets, shared-drive constraints, inherited access, and Google account
  capabilities remain part of the effective target boundary.
- Unsupported content conversions are reported truthfully; OCR and lossless
  arbitrary-format round trips are not promised.
- Whole-Drive access is the default file boundary when configuring Drive access.
  App-created and explicitly user-authorized files are supported as an alternative
  boundary with a file-selection entry point, as specified in REQ-10.
- Whole-Drive read requests and whole-Drive write requests remain distinct.
  The file-boundary default does not itself grant writing. A broad write grant may
  also admit sharing and ownership operations; no extra product permission is
  required or implied to exist.

### REQ-6. Preserve existing connections and actual grants during transition

The transition preserves valid saved connection identity, service state, ownership,
and actual grants, and replaces old selected-task execution ceilings with the
confirmed grant-derived model.

**Acceptance criteria**

- Saved Toolkit identity, connected Google account and client binding, owner scope,
  consuming-Agent relationships, personal access restrictions, namespace, enabled
  state, timeout, and unrelated metadata are preserved where applicable.
- An otherwise usable credential is not discarded solely because the execution
  transport changes; insufficient, revoked, or unverifiable authorization is
  reported and repaired through existing connection/reconnection management.
- Migration does not request or invent new Google scopes. It uses stored actual
  grant evidence, never the scope originally requested as a substitute.
- Within an enabled service, newly supported operations may become available under
  existing broad grants: for example sending under `gmail.modify` and sharing
  app-authorized files under `drive.file`. This is an intentional consequence of
  the confirmed model, not a claim that the old action set is unchanged.
- The changed capability projection is disclosed accurately in connection
  management. An old-effect ceiling is not retained as a hidden migration policy.
- Previously unselected services remain unselected, and disabled connections remain
  disabled. Previously permitted work remains available when its target and actual
  Google authorization remain sufficient.
- The whole-Drive default for new configuration does not expand an existing
  restricted-file grant during migration. Whole-Drive reading combined with
  app-file writing retains those actual scope boundaries; it is not upgraded to
  whole-Drive writing.
- Previously exposed schemas, conversation history, and pending connection work
  cannot activate removed authority or overwrite newer settings after transition.
- Completed connection outcomes remain inspectable without restoring historical
  credentials or permission selections.
- The transition itself performs no Google mailbox, event, file, sharing, or
  forwarding mutation.

### REQ-7. Immediate service controls and truthful Google access changes

Managers can disable services locally without new Google consent. Changes to
Google access use ordinary connection management and actual returned evidence.

**Acceptance criteria**

- After a service-off update succeeds, subsequently admitted operations obey it,
  including captured handlers and batch/compound operations.
- A remote operation already accepted by Google is not represented as undone.
- Previously installed filters or automatic-decline rules may remain active at
  Google; service off is not described as remote automation removal.
- Re-enabling uses current actual-grant evidence, not an assumption that all former
  permissions remain available or that old request bundles cap current grants.
- Missing scopes use ordinary reconnect. A service toggle with sufficient current
  grants does not force unnecessary Google consent.
- Merely unchecking an OAuth request bundle locally does not claim to revoke a
  previously granted scope or disable its tools. Google access changes are shown
  according to actual authorization evidence; a local service off is distinct.
- Partial grants enable only usable selected work. Unknown verification state is
  distinct from user denial, resource rejection, and account-feature unavailability.
- A cancelled or failed reconnect does not publish a fictional new connection or
  resurrect stale authority.

### REQ-8. Execution authority, credentials, and bounded file handling

Direct tools retain account and execution ownership, credential confidentiality,
and bounded file handling. The integration performs no Google-specific semantic
content screening of prompts, results, or original files.

**Acceptance criteria**

- Exposure and invocation both require current service selection, sufficient
  actual granted scopes, canonical Session execution ownership, Toolkit delegation,
  and personal access policy where applicable.
- Renewals, reconnects, permission reductions, and ownership changes cannot allow a
  stale success/failure to replace or invalidate a newer authorization state.
- Credentials are not returned in tool schemas, responses, logs, or ordinary Runtime
  scripts. Model input cannot switch the connected Google account.
- Tool contracts and data validation enforce supported inputs and bounded output.
  File and parser limits, authorized paths/resources, media handling and transfer
  integrity remain applicable independently of prompt-content screening.
- Text, schemas, tool arguments, and results are not rejected based on the removed
  Google-specific known-pattern prompt-injection rules. Original binary transfers
  are not rejected solely because that text scanner cannot inspect their bytes.
- No semantic prompt-injection, malware-free, or scanned-safe claim is attached to
  Google content or authorized file transfer. Provider content remains untrusted.
- Files use authorized Azents input/output boundaries, not arbitrary backend paths
  or credential-bearing provider upload/download links exposed as general tokens.
- Temporary failures and resource-level policy/ACL denial are not treated as global
  Google authorization revocation.
- Uncertain external writes are not automatically replayed after transport failure,
  reconnect, or failure to process a returned result.

### REQ-9. Coherent management and operator guidance

Connection setup and saved management explain the actual account, usable actions,
service state, and recovery paths for the direct integration.

**Acceptance criteria**

- Workspace-shared, Agent-owned, and personal-within-Workspace connections retain
  their existing management permissions and ownership boundaries.
- Shared-connection service changes make their cross-Agent effect clear.
- Operator preparation describes Google API/OAuth setup rather than requiring
  official MCP Preview admission.
- Requested access, actual Google consent, service state, and current usability
  are distinguishable. Scope-derived tool availability still respects supported
  operations, connected-account identity, Agent access, and resource constraints.
- Explanations follow real scope semantics. The UI does not offer independent
  drafts-only, sharing-off, or similar action switches when the actual model has
  no corresponding post-consent restriction.
- Existing setup/reconnect review and local disconnect semantics remain distinct
  from per-operation approval, which is outside this feature.
- Setup and operator guidance accurately describe the direct integration's
  protections. They do not retain obsolete claims that content screening occurs
  or require acknowledging a scanner that no longer exists.
- Uncertain saves or connection publication provide truthful outcome inspection
  rather than automatic mutation resubmission.

### REQ-10. Default whole-Drive access with optional selected-file access

Managers can retain whole-Drive access or choose Google-enforced access to files
created by or explicitly made available to the app. Existing-file selection is
available within Google connection management.

**Acceptance criteria**

- Whole-Drive is the initial file-access boundary for new Drive configuration;
  managers can deliberately choose the app-authorized-file alternative.
- In the limited alternative, a manager can open a file selector from connection
  settings, choose existing files to make available to the app, or cancel without
  treating the selection as successful.
- File selection establishes Google's app-file authorization rather than relying
  only on a local list under an unrestricted Google credential.
- Selection is associated with the intended connected Google account and app.
  Shared, Agent-owned, and personal management retain their existing authority
  boundaries; being a chat participant does not itself authorize file selection.
- The selector's authentication is handled through a secured authorized browser
  flow. Gmail or other unrelated service credentials are not exposed merely to
  enable Drive file selection.
- Previously authorized files can be used without selecting them again for every
  operation, subject to current Google authorization, service state, Agent access,
  and Google resource capabilities.
- File selection establishes target eligibility. `drive.file` may permit editing
  and sharing of that target; the UI does not imply an extra Azents action
  restriction or present that scope as selected-file read-only authorization.
- Selecting a folder is not represented as automatic recursive authorization to
  every existing or future descendant.
- No standalone file-management product, in-conversation file-selection interrupt,
  or per-operation approval flow is required.

## Fixed Constraints

- This snapshot concerns Gmail, Calendar, and Drive only.
- Existing account, ownership, partial-consent, no-secret-exposure, and no-uncertain-
  replay guarantees remain applicable.
- Actual OAuth grants are the action authority for supported tools inside enabled
  services. No second Azents selected-action policy is introduced.
- Direct-tool feature breadth is measured by supported effects, not matching the
  community project's 37 tool names or counts.
- No migration, live-account call, or production change is authorized by the design
  request itself.

## Confirmed Drive Product Choice

On 2026-10-21 the requester selected support for file selection with whole-Drive
access as the default. This determines REQ-5 and REQ-10. Existing grants are not
expanded to whole-Drive scopes merely because the default changes.

## Confirmed OAuth Authority Choice

On 2026-10-21 the requester confirmed that Google-approved scopes determine
supported tool availability within enabled services, rather than intersecting them
with a second Azents-selected action list. Request bundles shape OAuth requests;
they are not post-consent action ceilings. This supersedes the earlier exact
old-effect preservation and independently selected action-permission proposals,
including their migration assumptions. Actual grants, service state, ownership,
Agent access, resource capabilities, and supported-feature scope remain binding.

## Confirmed Content Handling Choice

On 2026-10-21, after comparing the community reference with official Google MCP
security documentation and the existing local scanner, the requester chose to
omit the Google-specific content scanner and its blanket binary rejection from
the direct integration. Model Armor is not added. Account/Agent access, OAuth
scopes, credential confidentiality, supported tool validation, file/resource
authorization, parser/size limits, and integrity checks remain applicable.

This product choice is not evidence of compliance with Google's policies. The
official MCP documentation's screening instructions and their applicability to
direct API use require a separate policy assessment before making compliance or
production-readiness claims.

## Open Assumptions

- Existing client-bound grants may suffice for corresponding direct API operations;
  this is subject to provider verification and is not proven by saved scope alone.
- Account plans, organization policies, file constraints, and format conversions
  may restrict individual actions without invalidating the entire connection.
- Migration implementation, pending-attempt handling, supported SDK selection,
  content-transfer mechanisms, and rollout boundaries remain technical decisions
  after requirement confirmation.

## Confirmation

Confirmed by the requester on 2026-10-21 before ADR and Design decisions began.
The requester subsequently confirmed the OAuth-authoritative simplification on
2026-10-21 and omission of the Google-specific content scanner on the same date.
The updated ten-requirement snapshot incorporates these changes while retaining
concrete action names and selective caution labels, no per-operation approval
workflow, and optional selected-file access with whole-Drive as default.
