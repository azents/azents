---
title: "Personal Tool Connections and Agent Access Requirements"
created: 2026-10-17
updated: 2026-10-17
tags: [toolkit, session, identity, security, frontend]
document_role: primary
document_type: requirements
snapshot_id: personaltools-261017
---

# Personal Tool Connections and Agent Access Requirements

- Snapshot: `personaltools-261017`
- Document reference: `personaltools-261017/REQ`

## Confirmation Status

The requester approved proceeding to technical design from the revised user experience on
2026-10-17. This repository Requirements snapshot translates that experience into observable outcomes.
The current scope is the requester's 2026-10-17 clarification: personal connections are confined to
the Workspace in which they are connected, even for the same User. A connection in Workspace A must
not appear in Workspace B or be available to B's Agents. Allowed Agents are configured independently
for each Toolkit within its own Workspace. This supersedes the earlier User-global interpretation
used by the initial implementation and Design revision 1.
The creation default remains **Allow all**, evaluated continuously for currently and subsequently
accessible Agents inside that connection's Workspace. The requester also
confirmed coverage of all currently configurable external Toolkit types and their existing supported
authentication methods, without a personal-only reduced catalog. The requester confirmed this
complete initial Requirements snapshot on 2026-10-17, including existing shared-result visibility and
the admitted-call withdrawal boundary. Those unchanged outcomes remain in force. The scope
clarification requires a corresponding ADR/Design correction before further implementation under
the corrected boundary. The requester selected a **Selected Agents** policy after the
first Agent restriction, as defined in REQ-2.
The requester also rejected personal-only feature differences: existing settings, authentication
methods and optional Runtime credential injection retain the same behavior for personal and shared
Toolkits. Personal ownership does not add Runtime isolation.

## Problem

A member can use shared Agent and Workspace Toolkits but cannot independently connect their own
external-service account and control which Agents may use it in their private conversations.
Delegating an account through a manager-owned shared Toolkit is not equivalent to owning a personal
connection. A conversation-local control would also misleadingly suggest that the delegation applies
only to one Session, while a new mobile header control competes with the existing Session title and
navigation.

## Primary Context

### Primary Actor

An authenticated member who can access an Agent and wants that Agent to use their own external-service
connection in their User Sessions without turning the connection into shared configuration.

### Primary Scenario

The member connects an external account as a personal Toolkit within one Workspace. The new personal
Toolkit defaults to **Allow all** within the member's accessible Agents in that Workspace, and the
member uses it in a User Session with an eligible Agent there. The member may restrict access to
particular Agents for that Toolkit. Entering another Workspace does not expose the connection or
reuse its allowance.
From within a conversation,
the member can open the same Agent-level personal-access settings, change the allowed connections,
and return to the conversation. The selection applies to that member's personal conversations with
that Agent, not to Team Sessions or another member's work.

## Supporting Scenarios or Effects

- The member inspects one personal connection in its Workspace context and manages its allowed Agents.
- The member reaches the same permission relationship from Agent navigation or an in-conversation
  shortcut and sees the same saved selection.
- Another member uses the same Agent without receiving the first member's personal connection.
- The owner reconnects an expired connection or removes a connection without changing shared Toolkits.
- Work resumes through recovery or continuation without selecting credentials from a new requester.

## Goals

- Make personal connection ownership and per-Agent delegation understandable and independently
  manageable by the owner.
- Make the personal connection's Workspace boundary visible while keeping permission management
  independently available by Toolkit and by Agent.
- Preserve discoverability from within a conversation without implying per-Session permission.
- Use personal credentials only under the correct User Session ownership and owner-controlled Agent
  access policy, with **Allow all** as the confirmed creation default.
- Preserve existing Workspace-shared and Agent-only Toolkit behavior and external-service authority.

## Non-Goals

- Approval prompts for individual Tool calls during Agent execution.
- Per-Session allowlists or one-off connection attachments.
- Delegating personal credentials to Team Sessions or other members by participating in a conversation.
- Reintroducing removed ambient-user MCP OAuth or GitHub per-request PAT compatibility paths.
- Turning external identity linking into consent for external-service actions.
- Replacing or migrating existing shared connections into personal connections automatically.
- A new general Agent/Workspace role system or cross-Workspace membership grants.
- Claiming that a private conversation provides filesystem or shared Agent Memory isolation.
- Replacing shared Runtime, shared Agent Memory, or existing resource ownership with a newly isolated
  personal execution product.
- Retrospectively deleting conversation results or undoing completed external actions on disconnection.

## Requirements

### REQ-1. Owner-managed personal connections within one Workspace

The User must create and manage their personal external-service connections within an explicit
Workspace context, separately from identity-only account links and shared Toolkit management.
A personal connection belongs to its User within that Workspace. It is not an account-global
connection that becomes available in other Workspaces.

**Acceptance criteria**

- Personal management provides a clearly personal, Workspace-scoped connection list, connection entry,
  safe external-account identity when available, connection readiness, and reconnect/disconnect actions.
- The same User's connection in Workspace A does not appear in Workspace B's management or
  Agent-access surfaces. Access to both Workspaces does not share personal connection ownership,
  credentials, configuration or allowance between them.
- Creating or managing the member's own connection does not require Workspace Toolkit-management or
  Agent-admin authority solely because it is a Tool connection.
- Only the authenticated connection owner may inspect or change private connection configuration,
  authentication state, or its Agent access relationship through personal-management surfaces.
- Workspace owners, Agent administrators, unrelated members, and guessed connection identifiers do
  not independently grant access to another User's personal connection.
- Credentials and authorization secrets are never rendered as ordinary connection details.
- Identity-only provider linking does not authorize personal Tool use.
- Using the same external account in another Workspace requires a distinct personal connection there.
  Creating a connection grants no new Workspace membership or Agent access.

### REQ-2. Default Allow all with owner-controlled Agent restrictions

A newly added personal Toolkit defaults to **Allow all** for its owner's eligible Agents in that
Toolkit's Workspace. The owner
must be able to inspect that policy and restrict which Agents may use the connection. The same
effective permission must be editable by connection or by Agent.

**Acceptance criteria**

- A newly added personal Toolkit visibly starts in **Allow all**, not an empty allowlist.
- **Allow all** applies only to Agents in the connection's Workspace that the owner may already
  access, and only in that
  owner's User Sessions. It never authorizes automatic personal-Toolkit selection in Team Sessions
  or another User's execution. It is not a Runtime isolation guarantee.
- Each Toolkit has its own active allowance policy and allowed-Agent relationship. Editing Toolkit A
  does not change Toolkit B, even when both have the same Provider, name or external account.
- Connection management identifies its Workspace and shows only eligible Agents in that Workspace.
  No Workspace search or cross-Workspace grouping is needed to choose allowed Agents.
- Agent-side management lists only the current User's personal connections within that exact
  Agent's Workspace.
- Saving through either management entry produces the same effective allowed relationship visible
  through the other entry; there are no independent per-page or per-Session permission copies.
- The UI identifies the Agent, Workspace, current owner, and application to all of that owner's
  personal Sessions with that Agent.
- Agent restrictions distinguish canonical Agents rather than matching by name.
- **Allow all** includes subsequently accessible Agents within the same Workspace, including new
  Agents there. It never expands to another Workspace. It is not a one-time copy of the Agent list
  at connection creation.
- Losing ordinary Agent or Workspace access makes the connection unavailable for that Agent even
  while the personal connection's **Allow all** policy remains enabled.
- Restricting an Agent while in **Allow all** changes the connection to **Selected Agents**. The
  currently allowed accessible Agents, except the restricted Agent, form the saved selection.
- In **Selected Agents**, subsequently created or newly accessible Agents are not allowed until the
  owner adds them. This differs intentionally from the ongoing **Allow all** default.
- An Agent-side edit that causes this transition identifies the resulting **Selected Agents** policy
  before saving; it does not silently present a global future-access change as a local exclusion.
- Selected-Agent access remains a connection-wide policy. User-side and Agent-side editors cannot
  maintain conflicting policy modes for the same connection.
- Granting access does not grant Agent, Workspace, Session, or external-service permissions otherwise
  absent from the relevant participant or connected external account.

### REQ-3. Agent-level settings with discoverable conversation entry

Personal Tool permission must be presented as the User's relationship with an Agent, not as a setting
owned by the conversation from which the User arrived.

**Acceptance criteria**

- Agent navigation provides a personal-access entry grouped with Agent identity and separated from
  the Sessions list.
- A conversation provides a shortcut through its existing composer add menu to the same independent
  Agent-level access page; the menu itself does not contain per-Session permission toggles.
- The access page displays Agent identity rather than the originating Session title and distinguishes
  personal access from shared Agent administration.
- Mobile adds no persistent personal-Tool button to the crowded Session header.
- Desktop and mobile expose the same ownership and permission semantics.
- Saving or cancelling from a conversation-originated entry returns to the originating conversation
  when it remains accessible; an invalid destination must not disclose another resource.

### REQ-4. Private execution resolves the Session-associated User's allowed connections

A User Session may use only personal connections owned by its durable associated User within the
executing Agent's canonical Workspace and allowed by that Toolkit's policy for the Agent, subject
to current access rules.

**Acceptance criteria**

- Team Sessions do not resolve personal connections as their Tool capabilities. Existing optional
  Runtime credential export retains its shared-process trust model rather than establishing
  isolation between Sessions.
- Another User's requester identity, message authorship, current view, Agent creation, approval, or
  Workspace ownership cannot select or replace the associated User's personal credential.
- Recovery, continuation, and subagent work preserve the same canonical User-root relationship; a
  broker wake-up or Tool argument cannot supply a different personal credential owner.
- Another Workspace's personal connection is not selected, discovered, invoked or exported merely
  because it has the same User owner, Provider or name. Listing, setup/callback admission, policy
  mutation, execution and later credential export all respect the connection's Workspace boundary.
- The connection's actual external permissions remain authoritative; Agent allowance does not expand
  the provider grant or bypass provider policy.
- Failure or absence of the selected personal connection does not silently switch the operation to
  another person's account or to shared authority.
- Existing shared Toolkit authority remains shared and is not silently converted into personal use.
- The control plane does not disclose private credentials through personal connection management,
  normal authentication metadata, events, errors or logs, or select them for another User's Toolkit
  execution. This does not promise to prevent a Runtime command from reading, printing or persisting
  credentials exported through an existing enabled Runtime-injection option.
- Existing shared Agent Memory and Runtime-file behavior remains unchanged. Personal connection
  ownership must not be represented as isolation of content that the Agent writes to those shared
  resources.

### REQ-5. Inspectable readiness, safe edits, and cancellation

The owner must understand whether a connection exists, is usable, needs reconnection, or is not yet
allowed for the selected Agent, and must be able to cancel uncommitted changes.

**Acceptance criteria**

- Empty connection and fully restricted access states explain the next action. New-connection
  completion clearly states the default **Allow all** consequence rather than requiring an
  additional per-Agent opt-in before eligible use.
- A User with no personal connections in the Agent's Workspace can navigate from Agent access to
  personal connection setup for that same Workspace.
- Cancelling an access edit preserves the previous saved relationship.
- Expected authorization, connection, and save failures are visible with a bounded retry or recovery
  action; an uncertain result is not reported as committed success.
- Reconnection preserves the personal connection's saved Agent policy while following the existing
  Provider's review, identity-change and confirmation behavior. Personal ownership does not impose
  a separate same-account-only reconnection restriction or bypass existing review.
- Search/filtering does not discard allowed selections that are temporarily outside the visible list.

### REQ-6. Withdrawal applies to future use without false retroactive guarantees

The owner must be able to withdraw Agent access or disconnect a personal account without affecting
unrelated personal or shared connections.

**Acceptance criteria**

- Removing one Agent's allowance prevents later personal Tool invocations through that relationship
  once the withdrawal is effective, including in a previously prepared Session.
- Disconnect confirmation explains which allowed Agents lose future use.
- Disconnecting removes the local connection's usable authority; a stale callback, refresh, prepared
  Tool, or old setup operation cannot restore the withdrawn grant without new owner authorization.
- The UI does not claim to undo an already admitted external action, erase previously returned
  content, or guarantee provider-side revocation solely because local access was removed.
- An external call already admitted under valid authority may finish after withdrawal. A later
  invocation must check current access and cannot rely solely on a previously prepared Tool.
- Withdrawal does not promise cancellation of an already admitted provider-side operation.
- Withdrawal applies to managed personal Tool dispatch and later credential export. It does not
  recall a token already handed to a running process, remove copies written by that process, or
  revoke provider credentials merely because local Agent allowance changed.

### REQ-7. Existing shared capabilities and visibility remain unchanged

Adding personal connections must preserve the existing management and execution contract for
Workspace-shared, Agent-only, and platform-owned capabilities.

**Acceptance criteria**

- Existing Toolkit resources retain ownership, grants, attachments, names, and authorization rules.
- An administrator's existing user-account GitHub delegation remains Toolkit-scoped and is not
  reinterpreted as the new User's personal connection.
- An unallowed personal connection is not made visible as another User's metadata or discoverable
  Tool source in Team or other User Sessions.
- Granting personal access does not change who can access a private Session or shared Agent data.
- Similar Provider types or connection names do not ambiguously replace one another at execution.

### REQ-8. Deterministic product verification and responsive access

The complete owner-connect, allow, use, withdraw, and recover journey must be verifiable without
requiring live end-user credentials in mandatory checks.

**Acceptance criteria**

- Verification covers two Users, distinct Workspaces/Agents, private and Team roots, root/subagent
  lineage, denied management, allowed execution, withdrawal, and stale authorization callbacks.
- The same User's personal connection in Workspace A is absent and unusable in Workspace B, including
  with guessed connection IDs, matching names, stale callbacks or prepared execution state.
- Both user-side and Agent-side permission entry points update the same effective relationship.
- Mobile entry, independent settings identity, selection search, save/cancel, and return navigation
  remain usable with keyboard/accessibility labels and without hidden primary actions.
- Provider interoperability checks are reported separately from deterministic local verification.

### REQ-9. Existing configurable external Toolkit coverage without personal-only exclusions

The personal connection feature must support the platform's configurable external Toolkits and their
currently supported authentication methods rather than selecting a smaller personal-only subset.

**Acceptance criteria**

- The baseline includes MCP, GitHub, Notion, Sentry, Google, Google Analytics, AWS, GCP, Kubernetes,
  and Brave Search. Google covers the services supported by its existing connection.
- Existing supported authentication alternatives are not excluded solely because the connection
  belongs to a User.
- Existing Provider settings and optional Runtime credential injection are also available with the
  same behavior. Personal ownership is not authority to hide or force-disable an existing option.
- In particular, a personal GitHub connection can use the existing Runtime environment-injection
  option for native `git` / `gh` authentication, with the same default and shared-Runtime risk model.
- Existing deployment registration, Provider availability, actual external grants, and external
  account/application requirements still apply; personal ownership bypasses none of them.
- A new external Provider is not implicitly ready for personal execution merely because it registers
  a name. The common personal ownership and authorization contract must be satisfied and verified
  without introducing an arbitrary product category of personal-ineligible external Providers.
- Platform-owned automatic capabilities such as Runtime, Memory, Skill, Goal, and Todo remain
  automatic capabilities rather than owner-created external connections.
- Shared-resource credential transport retains REQ-4's control-plane admission and redaction
  boundary while preserving existing explicitly enabled export behavior; the product does not
  claim personal-only secret isolation after credentials enter the shared Runtime.

## Fixed Constraints

- Personal Tool ownership is distinct from requester authorization, message provenance, shared
  Toolkit ownership, and the User Session's durable associated User.
- Generic execution context remains Userless; only explicitly User-owned capabilities consume the
  canonical User association.
- Agent access is an owner-controlled persistent relationship, not a per-call approval.
- Personal connections are User-owned within one Workspace. The new personal-Toolkit creation default
  is **Allow all** within that same Workspace.
- **Allow all** is personal-Session authority within existing access, not shared credential ownership.
- **Allow all** is ongoing and includes future accessible Agents in the connection's Workspace rather
  than a creation-time list.
- Once the owner restricts an Agent, the connection uses **Selected Agents** and does not inherit new
  eligible Agents. The initial default and the restricted policy have different future-Agent behavior.
- All currently configurable external Toolkit types and their existing authentication methods are
  in scope; there is no first release restricted to the screenshot examples.
- Current User Sessions share Agent Runtime resources and may use shared Agent Memory; this feature
  must not claim a new data-isolation guarantee without an explicitly confirmed outcome.
- Personal and shared Toolkits use the same existing Provider options, auth methods and Runtime
  injection semantics. Differences are connection ownership, management authorization, permission
  policy and which User Session execution may select the connection, not a new reduced feature set.
- Public repository artifacts must not include private product-document links, account identifiers,
  research transcripts, or credentials.

## Confirmed Result and Withdrawal Boundaries

- **Existing shared results:** REQ-4 preserves existing Agent Memory and Runtime-file behavior rather
  than adding a separate isolation product. Personal credentials and permission selection remain
  protected; results deliberately written to existing shared resources retain those resources'
  existing visibility. This is not a guarantee of noninterference between Sessions.
- **Withdrawal timing:** REQ-6 stops later invocations while permitting calls already
  admitted under valid authority to finish. It makes no remote rollback or in-flight abort promise.
- The requester confirmed these two boundary statements with the complete Requirements snapshot,
  separately from the earlier Provider-scope confirmation.
- **Runtime-export parity:** the requester rejected a proposed personal-only export restriction.
  Enabled credential export retains the existing shared-Runtime exposure and token-copy lifetime;
  User ownership is a management/selection boundary, not an isolation boundary for such exports.

## Open Assumptions

- No design mechanism may strengthen or weaken the result-sharing or withdrawal boundary without
  the relevant confirmed outcome.
- Provider-required external approval and consent remain independent of the excluded per-call Agent
  approval experience.

## Confirmation

The requester approved the revised user-experience direction and requested technical design on
2026-10-17. The initial snapshot used a User-global interpretation. The requester subsequently
clarified on the same date that personal Toolkits are connected within a Workspace: a connection in
Workspace A must not appear in Workspace B, including for the same User, and allowed Agents are
configured independently per Toolkit. This Workspace boundary supersedes the initial global
interpretation and its cross-Workspace future-Agent expansion.
New personal Toolkits still default to **Allow all**, superseding the earlier no-Agent draft default.
That ongoing policy includes future accessible Agents within the connection's Workspace only.
The requester further confirmed all existing
configurable external Toolkit types and existing authentication methods without a personal-only
subset. On 2026-10-17 the requester confirmed the complete Requirements snapshot as presented,
including unchanged shared-result visibility and allowing already admitted external calls to finish
after withdrawal while rejecting later calls. The requester subsequently selected Option B for
Agent restriction: transition from **Allow all** to a saved **Selected Agents** set, with no automatic
future-Agent inclusion in that policy. Initial implementation was submitted as unmerged phases under
the earlier global interpretation; the corrected Workspace boundary is not yet implemented or
verified. Design revision 1 approval does not authorize continuing under the contradicted scope.
The requester subsequently instructed that personal connections must not acquire different feature
restrictions, rejecting the proposed exclusion of optional Runtime token injection. REQ-4, REQ-6
and REQ-9 therefore preserve its existing semantics and scope the personal credential guarantee to
managed admission and control-plane handling, not new Runtime isolation.
