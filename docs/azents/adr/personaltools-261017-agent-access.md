---
title: "Personal Tool Connections and Agent Access Decisions"
created: 2026-10-17
updated: 2026-10-17
tags: [toolkit, session, identity, security, architecture]
document_role: primary
document_type: adr
snapshot_id: personaltools-261017
---

# Personal Tool Connections and Agent Access Decisions

- Snapshot: `personaltools-261017`
- Document reference: `personaltools-261017/ADR`
- Product authority: [personaltools-261017/REQ](../requirements/personaltools-261017-agent-access.md),
  confirmed by the requester on 2026-10-17.
- Mode: Collaborative. The requester owns unresolved material decisions.
- Accepted decisions: `personaltools-261017/ADR-D1`, `personaltools-261017/ADR-D2`,
  `personaltools-261017/ADR-D3`.

## Fixed and Derived Outcomes

- A personal external Toolkit belongs to one User globally, not to a Workspace or an Agent.
- All currently configurable external Providers and existing authentication methods are in scope;
  Provider registration and external-grant requirements still apply.
- Creation defaults to ongoing **Allow all**, covering currently and subsequently accessible Agents.
  The owner can restrict Agents, and ordinary Agent/Workspace access remains mandatory.
- Only the root User Session's associated User can supply the personal connection owner. Team roots
  and another User's execution cannot borrow the credential.
- Generic Engine, Worker, Run, ordinary Toolkit and turn contexts remain Userless. Personal capability
  admission must consume the canonical associated User through an explicit ownership boundary.
- User-side and Agent-side editors expose one permission relationship, not two permission authorities.
- In-conversation shortcuts navigate to independent Agent-level personal-access settings. No new
  persistent mobile header control, per-Session allowance, or per-call approval is added.
- Current permission must be revalidated for later calls after withdrawal. Preparation and a cached
  Toolkit instance do not authorize future effects. Already admitted provider calls may finish.
- Personal connection admission and control-plane handling remain owner-bound and redacted.
  Optional credential export retains existing shared-Runtime semantics under ADR-D3, not a new
  personal isolation guarantee. Existing Agent Memory and Runtime-file result visibility is preserved.
- Existing shared/Agent-owned connections and their authority remain unchanged. No silent credential
  fallback or migration of their ownership is permitted.

## Current-System Evidence

Baseline: `4fffac9133934f5b85027b50842b1dc5a48da3b2`.

- `rdb/models/toolkit.py:RDBToolkitConfig` requires `workspace_id`; nullable `owner_agent_id`
  distinguishes Workspace-shared from Agent-owned configuration. The detached Toolkit models also
  require a Workspace. The current ownership model cannot represent a global personal connection.
- MCP, GitHub user-account and Google current-grant rows reference `toolkit_configs.id`. Google and
  GitHub unpublished attempts also capture Workspace/Agent management context and Auth Session.
  Keeping the grant key alone does not make their admission logic owner-correct for personal setup.
- `engine/tools/deps.py:get_toolkit_registry` registers the ten configurable external Providers.
  `ToolkitProvider.resolve` uses validated config and a canonical per-source ResolveContext. This
  supports reusing Provider execution without copying every implementation.
- `repos/toolkit/data.py:EffectiveToolkitSource` currently has shared attachment and Agent-owned
  variants only. Effective source, allowed selection and namespace construction need an explicit
  personal path that cannot leak into generic shared discovery.
- `repos/memory/operations.py:resolve_associated_user_id` already follows subagent lineage to a User
  root and reads its associated User. It is evidence for the existing association model, not a
  general authorization capability by itself.
- `engine/tooling/session_toolkits.py` reconciles stable source keys and revisions and may keep a
  prepared instance across Runs. It does not by itself implement current personal allowance checks.
- `repos/toolkit_namespace.py` allocates durable Agent/Toolkit namespaces. Personal and shared
  sources of the same Provider must coexist without treating equal names as equal authority.
- `engine/tools/github.py:expose_env` and `engine/tools/builtin.py:_collect_secret_env` can send
  GitHub credentials to Runtime commands when explicitly enabled. The existing configuration
  describes its shared-resource leakage assumption. That path requires a separate feasibility and
  authority review for personal secrets; result-sharing permission is not secret-sharing permission.

## Material Decision Map

The three material topics in the briefed map are resolved. No remaining choice is authorized merely
by drafting the Design; a newly discovered material gap must be briefed before adding a mechanism.

- [x] **Accepted — canonical connection ownership and persistence.** Extend the canonical
  ToolkitConfig identity with explicit User ownership under ADR-D1.
- [x] **Accepted — restriction semantics around ongoing Allow all.** Transition to a Selected Agents
  policy on restriction, with explicit per-Agent membership and no future-Agent inclusion under
  ADR-D2 and updated REQ-2.
- [x] **Accepted — personal credential transport parity.** Preserve the existing optional Runtime
  injection behavior and shared-Runtime trust model under ADR-D3. No personal-only restriction,
  isolated Runtime or credential relay is introduced.

## Cross-Cutting Design Obligations

These are required or existing consequences, not new approval questions by themselves:

- Bind setup/callback/refresh/publication to the authenticated owner, exact credential target and
  permitted return destination; keep Provider I/O outside database transactions.
- Revalidate root User association, ordinary Agent access, current connection state and allowance
  before personal external effects. Cached discovery and namespace metadata are not authority.
- Preserve Provider scopes, refresh rotation and already-current credential replacement rules while
  preventing stale callbacks or refreshes from resurrecting withdrawn access.
- Keep shared/current public management contracts unchanged; personal management has explicit owner
  authorization rather than accepting caller-provided owner IDs.
- Account for deletion, access loss, Agent decommission, retries, current concurrent edits, recovery,
  subagents and two independent management entry points.
- Identify all schema, detached types, generated clients, API/tRPC, callback surfaces, effective
  source/catalog, Tool Search, hooks, tests and Specs affected by the selected decisions.
- Use existing source-revision and authority mechanisms where applicable; no new versioning system,
  feature flag, compatibility fallback or rollout mode is approved by this ADR.

## Agent-Owned Local Details

Equivalent helper and file boundaries, identifier spelling, DTO factoring, fixture naming, internal
pure transforms, and test organization are owned by the implementing Agent. They do not authorize
new ownership, public behavior, persistence, configuration, execution modes, or fallback paths.

## Considered Alternatives for Canonical Connection Ownership

Affected Requirements: personaltools-261017/REQ-1, REQ-4, REQ-7, REQ-9.

### Option A: One canonical ToolkitConfig with explicit ownership variants

Add a User-owned variant to the canonical connection identity and enforce mutually exclusive
Workspace-shared, Agent-owned, and User-owned ownership. A User-owned connection has no artificial
Workspace home. Reuse its canonical Toolkit ID for existing Provider configuration and current-grant
relations while introducing owner-correct management and execution projections.

Advantages:

- One Provider configuration, credential and current-grant identity model supports all external types.
- Existing OAuth grant FKs and Provider context identities can remain canonical rather than be
  duplicated or accepted through polymorphic loose IDs.
- Existing shared/Agent-owned rows can retain their identities and ownership through an additive,
  constrained ownership migration.

Costs and risks:

- The universal Workspace assumption in detached models, CRUD, OAuth attempts and authorization must
  be replaced with explicit typed ownership; changing only nullability would be insufficient.
- Shared/Agent management and discovery must exclude the User-owned branch even for administrators.
- Existing clients and contracts must be checked so personal optionality does not leak into unchanged
  Workspace-only responses.

### Option B: Separate personal connection aggregate

Keep current ToolkitConfig Workspace-only, and store personal connections in a separate aggregate.
Share Provider adapters and typed execution inputs where safe; generalize OAuth/grant storage or use
separate owner-specific persistence without borrowing a shared Toolkit's credentials.

Advantages:

- The existing Workspace invariant and management queries remain structurally narrow.
- Personal management ownership is independently visible in its persistence boundary.

Costs and risks:

- MCP, GitHub and Google grants currently FK to ToolkitConfig; a separate aggregate needs an explicit
  shared credential-parent design or separate dependent storage and corresponding lifecycle work.
- Provider-neutral configuration, naming, discovery, credential lifecycle, cancellation and callbacks
  require extra adapters or parallel aggregates, increasing the burden of all-Provider coverage.
- Creating a hidden Workspace Toolkit as a surrogate would violate the global personal-owner model;
  it is not an admissible shortcut under either option.

### Recommendation Presented

Recommend Option A because all configurable external Toolkit types and existing authentication modes
are required, and current grants and execution already use one canonical Toolkit ID. The owner model
must be explicit and constrained rather than an ambient nullable User field.

## personaltools-261017/ADR-D1. Extend canonical Toolkit ownership

Accepted by the requester on 2026-10-17 after reviewing Options A and B.

Affected Requirements: personaltools-261017/REQ-1, REQ-4, REQ-7, REQ-9.

### Decision

Choose Option A. User-global personal connections are a first-class ownership variant of the existing
canonical ToolkitConfig rather than a second personal connection aggregate.

- Distinguish Workspace-shared, Agent-owned and User-owned connections through explicit constrained
  ownership. A User-owned connection has no synthetic Workspace home or shared-manager owner.
- Reuse one canonical Toolkit ID and the existing Provider configuration and authentication-grant
  identities. Provider-specific setup admission and callbacks must nevertheless become owner-correct.
- Keep management owner identity separate from the User Session association used for personal
  execution. This decision does not add User identity to generic execution context.
- Existing Workspace and Agent resources retain their IDs, owners, grants and behavior. Their public
  management responses do not acquire personal connection visibility.
- Apply the ownership invariant consistently in database storage, detached models, repository
  predicates, services, routes and execution projections. Merely adding a nullable field is not a
  sufficient implementation of the decision.

### Rationale

All external Toolkit types and existing authentication modes must be supported. Current MCP, GitHub
and Google grants and namespace relations already depend on the canonical Toolkit ID. Extending
explicit ownership keeps those identities and Provider behavior reusable while making the new
authorization branch explicit.

### Rejected Alternative

A separate personal aggregate would preserve the old Workspace-only invariant, but require an
additional canonical grant-parent model or parallel grant lifecycle/adapters for full Provider
coverage. Its structural separation does not justify that duplicate ownership and lifecycle surface
for this feature. A hidden home-Workspace surrogate is also rejected because it contradicts global
personal ownership.

### Consequences and Verification Obligations

- A forward ownership migration and explicit constraints are required, preserving existing resources.
- Audit every mandatory-Workspace assumption in Toolkit CRUD, setup attempts, callback state,
  refresh/current-grant admission, effective source and namespace selection.
- Owner-only personal management and shared management must not admit one another's resources,
  including guessed IDs, old callback parameters and privileged Workspace roles.
- Verify existing shared/Agent-owned response and lifecycle behavior alongside all personal Provider
  journeys. Changing persistence authority is not proof that every Provider is feasible yet.

## Considered Alternatives for Restricting One Agent under Allow all

The default and its future-Agent expansion are already confirmed. What happens after the owner
turns off one Agent is not yet specified. This affects the lifetime of permission, not just row
encoding; update Requirements with the owner's answer before accepting any corresponding technical
representation.

### Option A: Keep the all-eligible policy and exclude particular Agents

Turning off Agent A excludes that Agent only. Existing other Agents and future accessible Agents
remain eligible. Turning A back on removes its exclusion. Two entry points edit the same relationship.

This keeps an Agent-side edit local to the named Agent and preserves the ongoing default for all
others. The UI must label the resulting policy accurately, such as all eligible Agents except the
listed restrictions, rather than falsely showing unrestricted Allow all.

### Option B: Move to an explicit selected-Agent policy after restriction

Restricting A transitions the connection into selected-Agent access. Other currently selected Agents
remain eligible, but future Agents are not implicitly included until the owner chooses them.

This supports strict opt-in after customization, but introduces an additional policy mode and changes
future-Agent treatment as a consequence of an Agent-side edit.

### Recommendation Presented

Recommend Option A: the caller's edit affects only the named Agent and does not silently change
future-Agent behavior elsewhere. Option B is not approved merely because it is easy to encode as an
allowlist. The requester selected Option B instead, as recorded in ADR-D2.

## personaltools-261017/ADR-D2. Persist All or Selected-Agent permission

Accepted by the requester on 2026-10-17 by selecting Option B. The product outcome was first recorded
in personaltools-261017/REQ-2 before accepting this representation.

Affected Requirements: personaltools-261017/REQ-2, REQ-3, REQ-4, REQ-5, REQ-6.

### Decision

Use two explicit connection-wide permission states: **Allow all** and **Selected Agents**.

- New personal connections start in Allow all. Eligibility is evaluated against current ordinary
  access rather than copied into an initial Agent list.
- Restricting one Agent under Allow all atomically switches the connection to Selected Agents and
  saves the current eligible selection minus the restricted Agent. It is not an all-with-deny-
  exceptions model.
- Selected Agents persists positive membership for exact canonical Agents. Future Agents and new
  Workspace memberships do not add membership implicitly.
- Store the policy on the User-owned canonical Toolkit and store selected Agent membership as its
  dependent permission relation, separate from shared AgentToolkit attachments.
- User and Agent editors operate on this one authority. An Agent editor may propose a one-Agent
  change, but the resulting connection-wide policy is explicitly reflected before commit.
- Authorization is the conjunction of User ownership/root association, active connection/current
  credential, current ordinary Agent access, and the saved policy. Selected membership does not
  bypass access loss.
- Commit a policy transition and its selected membership as one database operation. Filtered pages,
  independent editor state and stale client lists cannot silently replace unseen membership.

### Rationale

The requester explicitly chose a selected-Agent policy after customization, preferring future opt-in
over continuing all-eligible access with exceptions. A first-class policy plus positive membership
preserves the dynamic All default without treating an initial empty membership table as deny-all or
mistaking a saved selected set for future-inclusive access.

### Rejected Alternative

All-with-specific-exclusions was recommended, but the requester selected the other future-access
behavior. A deny-exception model would therefore be a different product policy and is not retained
as another hidden permission authority.

### Consequences and Verification Obligations

- Verify All -> Selected conversion across multiple Workspaces, excluding the edited Agent and
  preserving other currently eligible Agents without silently limiting to one search page.
- Verify a newly accessible Agent is eligible under All but not under Selected.
- Verify simultaneous edits cannot yield mixed policy/membership, and selection search/cancellation
  does not drop unseen membership.
- Verify ordinary access loss denies both modes, and both editor entry points project the same
  result. Do not add a separate versioning system or compatibility mode to implement these checks.

## Rejected Proposal: Personal-only Runtime Export Restriction

The following records the proposal presented and rejected by the requester. ADR-D3 supersedes the
proposed restriction and resolves the earlier isolation conflict through explicit existing-behavior
parity in Requirements.

### Evidence and Conflict

- `core/tools.py:GitHubToolkitConfig.inject_runtime_environment` defaults to false. Its documented
  enabled behavior injects `GH_TOKEN` / `GITHUB_TOKEN` into Runtime child processes and explicitly
  assumes no isolation.
- `engine/tools/github.py` exposes both installation/PAT and GitHub user-account credentials through
  `expose_env` when configured. `engine/tools/builtin.py` collects those peer credentials and passes
  them as the Runtime child-process environment.
- A personal connection's API/MCP authentication can remain worker-side across the existing GitHub
  auth methods. Automatic shell-token export is an additional Runtime integration option, not a
  separate authentication method.
- Passing a personal token to a command in the shared Runtime permits that process to read, print or
  persist it. This cannot be described as preserving the confirmed personal-secret boundary solely
  because the originating Session is private.

### Proposal Presented and Rejected

Support all existing personal Toolkit types and authentication methods for their Tool/API execution,
but do not provide automatic personal-credential export to shared Runtime commands. In particular,
personal GitHub connections would not populate `GH_TOKEN` / `GITHUB_TOKEN` for native `git` / `gh`.
Existing Workspace-shared and Agent-owned export options would remain unchanged.

This preserves the current no-new-isolation scope and avoids a new credential proxy or intermediary
service. It changes the available optional personal Runtime integration experience, so it must be
confirmed in Requirements rather than silently treated as a local implementation detail.

The requester rejected this personal-only difference. No extra Runtime, credential relay or
personal-specific fallback is authorized by that rejection.

## personaltools-261017/ADR-D3. Preserve Provider and Runtime-injection parity

Accepted by the requester on 2026-10-17 by rejecting personal-only feature differences after the
Runtime-export consequences were explained. Requirements REQ-4, REQ-6 and REQ-9 were updated first.

Affected Requirements: personaltools-261017/REQ-4, REQ-6, REQ-7, REQ-9.

### Decision

- Personal and shared connections use the same existing Provider configuration, authentication
  methods and optional Runtime environment-injection functionality.
- A personal GitHub connection may use `inject_runtime_environment` with the same default and
  semantics as an equivalent shared connection. Do not hide, reject or override that option based
  solely on User ownership.
- Personal selection and current allowance are checked before managed dispatch and before later
  credential export. Once an enabled export passes credentials to a Runtime process, the process
  operates under the existing shared-Runtime trust model.
- Do not describe User Session ownership as preventing that process from reading, printing or
  retaining exported credentials. Local withdrawal cannot recall copies or provider authority
  already exported; it governs later managed admissions.
- Keep control-plane responses, normal authentication metadata and logs redacted. Existing warnings
  and configuration semantics remain applicable without a new personal-only confirmation flow.
- Add no isolated Runtime, credential proxy, background relay, special fallback or personal-only
  feature gate.

### Rationale

The requested feature changes ownership and eligible execution selection, not Provider
functionality. The proposed export ban would introduce an unrequested difference between personal
and shared connections. Preserving the existing option requires preserving its actual trust
boundary rather than claiming new isolation that the system does not provide.

### Rejected Alternative

Disabling optional Runtime token injection only for personal connections was explicitly rejected.
Building an isolated execution or credential-relay product to preserve a stronger secrecy promise
is outside the confirmed scope.

### Consequences and Verification Obligations

- Verify enabled and disabled injection for every existing GitHub authentication family with fake
  tokens, without logging or retaining live token values in evidence.
- Verify invalid personal admission never collects or exports its credentials; ordinary shared
  environment behavior remains unchanged.
- Verify later export rechecks current allowance, while an already started process is not falsely
  claimed to be revoked or erased.
- Reflect this parity and shared-Runtime limitation accurately in the final Design and test report.
