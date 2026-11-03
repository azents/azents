---
title: "External Channel authorization"
created: 2026-07-22
tags: [backend, frontend, external-channel, authorization, security, discord]
---

# External Channel authorization

External principals, approval decisions, scoped grants and exact-binding release authority.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [External Channels](../domain/external-channel.md)
- [Users and authentication](../domain/user-auth.md)
- [External Channel ingress](external-channel-provider-ingress.md)
- [External Channel delivery](external-channel-delivery.md)

## Principal Boundary

Selector catalog projection and Discord component scope checks complete native
PostgreSQL read-only operations before returning detached authorized data.
Immutable route selection, setup-route assignment, default creation and related
interaction/claim changes remain repository-owned writable atomic groups with the
existing actor, active Agent, connection, resource, selection and terminal-state
predicates. Participation settings use completed repository operations:
independent settings, claim and thread-scope reads finish before external
coordination or provider work; parent, thread and location mutations retain
their exact generation or timestamp conditional updates and database lock order.
Provider cleanup intents and setup replay execute after commit. Descriptive reads
may observe previously committed state while a writer holds a row lock; they do
not authorize a future mutation without that mutation's existing revalidation.
No provider actor becomes an execution User and no route/access or response-mode
fallback is introduced by this ownership boundary.

An External Channel participant is an `ExternalChannelPrincipal`, not an Azents User
or WorkspaceUser. Provider identity is scoped by provider tenant and user ID. Human,
bot, app, and system authors are retained separately.

Every dedicated route has one automatic author-admission setting:

- `open_access_enabled` defaults to `true`. A human author may invoke the routed
  Agent without a per-principal grant unless an active block applies.

Only human authors are eligible triggers. Bot, app, and system callbacks never create
selector or approval state and do not consume the conversation read position. The
connected Azents provider bot is excluded from provider-history projection, preventing
output loops. Trigger eligibility is separate from contextual visibility: other
provider-visible humans, bots, and supported system messages remain in a later eligible
human invocation's bounded history. Blocks take precedence over grants and automatic
route access. A grant continues to authorize an eligible human when automatic route
access is disabled.

Only a human Multi App invocation can create selector state in its owning interaction.
For channel setup, the selector is linked to the latest-source setup claim and may
create the first provider-principal-authored channel default only from routes the
initiating principal may invoke. It then moves the claim to `pending_location` without
Binding replay. Legacy isolated-thread selectors without a setup claim retain their
resource-bound replay behavior. Duplicate source callbacks validate and reuse current
state; they never clear or silently replace an already selected route.

The authenticated Azents administrator who grants or revokes access is a requester for that public
management operation only. Neither the administrator nor the ExternalChannelPrincipal becomes an
execution User. Once authorized work is durable, the linked Team Session is executed by the canonical
Session/Agent/Workspace/root-tree/Run snapshot after owner-generation claim. A broker wake contains
only `session_id`; it cannot carry or override provider, principal, requester, Agent, Workspace,
prompt, or resource authority.

## Restricted Human Flow

When `open_access_enabled` is disabled, an unknown human invocation cannot create an
AgentSession, binding invocation, or Agent wake-up until a grant is created. The
request retains an immutable provider-history replay boundary instead of a mutable
pending-context buffer. With the default open-human policy, an eligible unblocked
human follows durable DB-only admission directly.

When a restricted participant invokes the Agent:

1. An exact bound thread proceeds directly. An explicit top-level invocation with a
   selected route but no participation setting creates or replaces one setup claim.
   An unresolved Multi App invocation first requires one explicit selector interaction
   and validates the chosen route. Slack presents its selector through Block Kit;
   Discord uses a verified command or component interaction.
2. Admission creates one idempotent access request for the selected route and
   metadata-only provider-history source identity.
3. The request snapshots the connection, conversation position, exclusive range start,
   and inclusive trigger position, expires after seven days, and contains an opaque ID.
4. The access request conservatively preclaims its current control projection as
   `unknown`, then returns one process-local provider control plan with the participant
   display label, complete provider user ID, and an authenticated Azents approval URL
   rendered through the provider's safe control shape. A delivered result stores only
   the current provider message key and projection status on the request. Pending
   selector and approval rows contain no provider body, revision, attachment metadata,
   reference mappings, or original-message URL.
5. The approval page requires an authenticated user who is an administrator of the routed Agent. Unauthorized, cross-Agent, missing, and expired requests do not disclose the request and appear not found or unavailable.

Selector completion does not grant access. It preserves the original sender and
uploader provenance, then applies the chosen Agent's existing grant, block, and
approval policy. The Slack or Discord callback actor can confirm interaction scope but
never becomes the execution User or replaces the initiating principal.

## Decisions

Supported decisions are `allow_session`, `allow_agent`, `deny`, and `block`.

- **Allow Session** grants the principal only for the proven AgentSession scope. For
  legacy configured-thread requests it creates or reuses the Resource Binding.
- **Allow Agent** grants the principal across connected Bindings for that Agent. For
  legacy configured-thread requests it creates or reuses the Binding.
- **Deny** resolves only the current request.
- **Block** resolves the request and creates an Agent-scoped block that takes precedence over grants.

The decision transaction first resolves the request identity, then locks and
revalidates the route connection, active Resource and Binding, optional setup claim,
and the same request. It verifies the operation-permitted connection state, available
route, active Resource, active Agent, principal authorization, and current setup source
revision. A setup-linked Allow writes the grant and decision atomically, then resumes
the same claim at `pending_location`; it creates no Binding, Session, mailbox input, or
AgentRun and cannot enter `replay_access_allow`. A legacy configured-thread Allow may
create the External Channel AgentSession and connected Binding atomically. Repeating
the same compatible decision returns the existing authorization state. Conflicting or
stale decisions return a conflict instead of creating parallel state.

When a legacy Allow needs a new Binding, the shared root Session creation boundary reads the
routed Agent's current automatic Project policy and creates the root
`SessionAgentContext` Project snapshot before the binding commit. It performs no
Runtime validation or filesystem access in this transaction; policy save-time
validation is authoritative. If the resource already has a connected binding, Allow
reuses that binding's Session and context snapshot instead of rereading or merging
the current policy. A newly created Binding also copies the routed Agent's current
required External Channel response-mode default. Reusing a Binding retains its
existing concrete mode. Setup-linked Allow defers both snapshots until selected setup
replay creates the configured Binding.

When the original approval control message has a delivered provider identity, every
compatible final decision also returns one access-request-origin direct delete plan
from the decision transaction. The provider delete is attempted only after the
decision commits. Failed or ambiguous deletion updates only the request's current
control projection, never rolls back the authorization result, and creates no retry or
recovery work.

## Durable Replay and Context Release

Legacy configured-thread Allow commits authorization before replay and then calls the
shared DB-only ingress admission service with the request's immutable
conversation-position boundary. The decision may create the root Session and Binding,
then inserts or reuses one content-free active ingress item for that exact Session.
Provider history, cursor advancement, per-message mailbox admission, and Session wake
occur later in the leased Session drain.

If the shared position is still before the trigger, the drain reads forward normally;
if another accepted invocation advanced past the trigger, the provider policy uses the
saved range start and exact trigger boundary. Both position cases converge through the
active-ingress deduplication key, conversation-position CAS, and deterministic
provider-message mailbox identities.

When the decision created the root Session and Binding, only the exact eligible human
mailbox row whose `prompt_role` is `invocation` may carry initial automatic-title
eligibility. A repeated compatible decision, an existing Binding, or replay recovery
does not re-arm eligibility. Repeating a compatible Allow may resubmit the same Session
execution key to recover a post-commit submission or provider-resolution failure, but
active-ingress and mailbox identities prevent another logical input or execution.
The replayed item's saved exact trigger identity participates in the same active
correlation as normal ingress and therefore cannot be demoted to context during
provider-history hydration.
Replay failure never reverts the already committed access decision or Binding, and it
does not couple provider-control success to accepted mailbox execution.
This durable replay remains available while connection ingress health is `active`,
`degraded`, or `reconnect_required`; `configuring`, `disconnecting`, and `disconnected`
connections cannot start it. Transient Gateway or Socket recovery therefore does not
revoke already committed replay and outbound REST authority.

The resulting canonical messages each use one `external_channel_message` mailbox row
with `wake_session` scheduling, explicit FIFO group/sequence, provider source
attribution, trigger identity, `prompt_role`, and one optional leading omission
reminder on the first retained context row. A non-empty processing batch sends one
post-commit routing wake; pending mailbox state remains recoverable when that wake
fails.

Later authorized original messages on a connected `all_messages` binding create
another active ingress item and later one mailbox row per canonical provider message
before waking the same Session. The exact admitted ordinary trigger is projected as
`prompt_role=invocation` even though it has no provider-native explicit-invocation
signal; earlier retained messages remain context unless independently correlated to
another admitted trigger. A `mention_only` binding
requires an explicit invocation; ordinary messages remain provider-history context
without independent admission. Edit and delete callbacks are excluded in either mode;
they do not independently invoke the Agent or create a lifecycle/revision correction.

## Response-Mode Management Authorization

The Agent default and each connected binding mode use the existing External Channel
management authority. Reading the Agent-scoped default follows Agent visibility.
Replacing the default or a binding mode requires an explicit AgentAdmin relationship.
Binding mutation additionally scopes the row to the requested Workspace, Agent,
AgentSession, binding ID, and `disconnected_at IS NULL`. Unauthorized, cross-scope,
missing, and disconnected targets remain indistinguishable through the existing
not-found response. Neither mutation changes grants, blocks, route access policy,
principal identity, past messages, or already accepted work.

Provider-native setup and settings use a separate principal-authorized service around
the same repository mutations. Parent operations require the selected route and active
setting generation; thread operations require an exact connected Binding. Open access,
an Agent grant, or a same-Session grant for the proven target may authorize the
operation, while blocks always win. A Session grant cannot establish an unrelated new
parent setting, and an unproven thread scope never falls back to parent mutation.

Discord connected-setting controls additionally bind the originating authenticated
interaction, operation category, current setting or Binding identity, and revision
fence. The selected String Select value comes from the newly signed interaction and
must belong to that operation's closed value set. Thread controls re-prove that the
signed Binding owns the exact Discord delivery Thread before mutation. A successful
response may expose `View session` only from the authorized route's exact connected
Binding, current Agent, and current Workspace; parent settings omit navigation when
there is no single parent Binding.

## Linked Account and Shared Model Settings Authorization

Ordinary linked-account/settings inspection and draft editing use scoped
descriptive authorization without blanket parent/link/User/grant read locks.
Draft edits condition persistence on the existing exact identity, active status
and expiry. Actual OAuth link finalization and model-setting apply perform their
own final mutation guards, retaining exact User/auth-session/link eligibility,
block/grant and route lifecycle authority through commit. These final guards do
not become authority for later ordinary descriptions or bypass the independent
captured-model input acceptance.

Optional external-account linking is an additional identity proof, not an admission
policy. Every existing principal grant, block, open-access decision, setup control,
response mode, and location mutation remains authorized independently. An unlinked
human retains those guest capabilities, and a link never makes the provider
principal an execution User.

The native link origin is created only from a verified human Slack or Discord
interaction and binds connection generation, provider tenant/user identity,
principal, and original interaction. The browser locator carries no identity proof.
An elevated Azents User stages an immutable candidate bound to the current auth
Session; only a hash of its one-time code is durable. The original signed provider
actor proves the code, and the same live elevated User/auth Session explicitly
confirms the candidate. Finalization locks and revalidates current account,
membership, origin/candidate, connection generation, and active uniqueness in one
commit. Conflicts and cross-user lookup remain nondisclosing.

A linked human may open and Apply private model settings only for the exact connected
Binding and root Session for which provider participation and web-equivalent User
authority succeed. Editor/draft descriptions use ordinary authorization reads and
private draft persistence retains its live expiry/unapplied/uncancelled conditions.
Actual Apply revalidates active User, membership, link, connection, Resource,
Binding, Session, Agent, model options, grant/block policy, actor and draft ownership
under its exact final mutation guards. The existing Agent/principal authorization
key protects absent-row block creation and grant deletion through final acceptance;
it is not inherited by ordinary participation descriptions. Relevant revoke,
account, unlink, archive and configuration writes remain ordered with actual Apply.
Final native mutation fences use ordinary waiting acquisition, including the
same-key authorization advisory fence. Routing rows precede the advisory fence,
which precedes Principal/Agent exclusion; linked User precedes Link and Agent
precedes root Session. Locked identities, complete authorization and DB-current
draft expiry are revalidated after waiting. The existing 250ms per-acquisition
lock timeout and three DB-only attempts return the existing retryable busy result
on exhaustion without mutation or provider I/O; they are not a total-operation
deadline. Draft reopen also refreshes authorization and expiry after its write
wait. An observed applied-profile generation rejects stale and ABA drafts.

Authenticated OAuth claim and finalization remain separate DB operations around
one provider exchange. Claim waits in Section -> User -> auth Session -> exact
OPEN Attempt order, then checks current expiry and exact context before consuming
state. Finalization uses the same authority order followed by the active identity
Link, rechecking current User/auth Session authority after the final wait. A
temporary holder is not a reason to exchange the code again. No new local claim
timeout or post-exchange Attempt-expiry contract is added; cancellation and genuine
authorization loss remain failures. Finalization keeps its existing DB-only
retry/uniqueness reconciliation and provider work remains outside it.

Owner unlink uses exact-owner conditional revocation DML with ordinary row
waiting and the existing bounded database retry/busy contract. Already-revoked
matching links retain their original revocation metadata. Current User/auth
Session and elapsed expiry are revalidated after a write wait before commit.
Matching accepted-model mutation replay observes immutable committed identity
and profile/audit values without a redundant exclusive replay-row lock.
Final authorization, unique Apply identity and once-only generation/audit/notice
remain authoritative; neither simplification retries provider effects or adds
a new OAuth callback recovery contract.

Execution-option group metadata does not grant model or integration authority.
Private model handlers validate exclusive selections against the bounded selected
option definitions and the shared registry before applying a profile mutation.
Normal clears only the identified supported group; forged conflicts and unknown
groups do not change the previously applied profile or authorization context.

## Revocation

Agent administrators can revoke active grants or remove blocks. Grant revocation
locks and deletes the selected grant row, preventing future invocation without
deleting canonical messages, projected Session history, or unrelated grants.
Binding and connection disconnect remain separate lifecycle operations.
Owner unlink is terminal and immediately removes future link-based model authority,
but does not alter guest grants/blocks, prior messages, the already-committed shared
profile, or immutable mutation audit.

## Scheduled Task Authorization

Scheduled Task creation and replacement accept only an exact active Binding
already connected to the selected Session and Agent. The opaque Binding ID is
never resolved by label, provider coordinate, parent conversation, or fuzzy
matching. Public API and Agent-tool paths both fail closed when the Session,
Binding, route, resource, connection, or Agent authority is stale.

Signed Slack and Discord registration controls carry the exact Task and Binding
identities but no actor or provider credential. Callback handling revalidates the
provider principal, durable interaction, current Task target, and exact connected
Binding before Edit or Delete. A valid provider principal for another Binding or
Session cannot mutate the Task.

## API route entrypoints

- `/external-channel/v1/approval-requests/{access_request_id}`
- `/external-channel/v1/approval-requests/{access_request_id}/decision`
- `/external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access`

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/repos/external_channel`](../../../../python/apps/azents/src/azents/repos/external_channel)
- [`python/apps/azents/src/azents/services/external_channel`](../../../../python/apps/azents/src/azents/services/external_channel)
