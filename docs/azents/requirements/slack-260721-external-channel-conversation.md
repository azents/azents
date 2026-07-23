---
title: "External Channel Agent Conversation Requirements"
created: 2026-07-21
updated: 2026-07-21
tags: [slack, integration, agent, security]
document_role: primary
document_type: requirements
snapshot_id: slack-260721
---

# External Channel Agent Conversation Requirements

- Snapshot: `slack-260721`
- Document reference: `slack-260721/REQ`

## Problem

Azents Agents can currently be used through Azents sessions, but teams also discover problems, coordinate work, and review outcomes in external collaboration channels. Users need to start and continue Agent work from those channels without turning every Azents response into an automatic external broadcast, losing the surrounding channel context, or granting unreviewed users access to an Agent's capabilities.

The first release must provide this experience through a dedicated Slack App connected directly to an Agent, while establishing product behavior that can later support multiple Slack installations and other channel types such as Discord, GitHub comments, and Jira.

## Primary Actor

An approved Slack workspace participant who needs to ask a connected Azents Agent to investigate or perform work from a Slack channel thread.

Supporting actors are the Agent owner who configures the Slack connection and the authorized Azents user who approves or blocks previously unknown Slack participants.

## Primary Scenario

1. An Agent owner creates and installs a dedicated Slack App by following Azents guidance, then connects its credentials to the Agent.
2. A Slack thread contains an automated error notification and discussion from multiple human participants. An unknown Slack participant mentions the Agent to request an investigation.
3. Azents does not start the Agent yet. It presents an approval entry point to an authorized Azents approver.
4. The approver grants the Slack participant session-only or Agent-level access. Azents creates an Agent session when the thread is not already linked, imports the relevant existing thread context, and delivers the original request.
5. The Agent explicitly sends a Slack reply indicating that it will investigate and publishes a channel-specific task list. The task list is shown in a separate progress message in the Slack thread.
6. The Agent continues the work across runs and context compaction while unfinished channel tasks remain. Task updates modify the existing progress message.
7. Additional approved-user messages in the same Slack thread join the same active channel work without requiring another mention. Messages from other humans and bots remain available as attributed context but do not independently invoke the Agent.
8. The Agent explicitly sends its final Slack response and completes or clears the task list. Azents stops automatic continuation and deletes the temporary Slack progress message.
9. Authorized Azents users may continue the same Agent session on the Web without ordinary Web conversation being automatically published to Slack.

## Supporting Scenarios

- An approved participant asks a question that can be answered immediately; the Agent explicitly replies without creating follow-up tasks, and no continuation remains active.
- The Agent explicitly decides that an inbound Slack request requires no response; no Slack reply is sent and no continuation remains active.
- One Agent is connected to multiple Slack Apps or workspaces and, later, to multiple provider types at the same time.
- A session contains multiple linked external conversations, each with its own current channel work and progress state.
- An unapproved participant contributes context that an approved participant later references; the Agent can use the attributed context without treating the unapproved message as an instruction.
- A blocked participant posts or mentions the Agent; no approval prompt, Agent run, or Agent response is produced for that participant.
- An owner disconnects one linked Slack thread or the entire Slack App connection while retaining the historical Agent session and imported conversation.
- Future channel adapters may link an external resource created during Agent work, such as a GitHub pull request, back to the same Agent session. Implementing those adapters is outside this snapshot.

## Goals

- Let approved Slack participants begin and continue Agent work naturally from a channel thread.
- Preserve complete, attributed thread context without granting every participant or bot authority to invoke the Agent.
- Require explicit Agent actions for all outbound external-channel communication.
- Make long-running follow-up work and its current progress visible in Slack.
- Prevent the Agent from forgetting unfinished external work across runs, compaction, additional input, or worker recovery.
- Support multiple independent external-channel connections and linked conversations per Agent.
- Give Agent owners and authorized users clear approval, revocation, blocking, channel-management, and disconnect controls.
- Preserve Azents Web conversation privacy when a session is also linked to an external channel.
- Make external-channel messages visibly and semantically distinct from ordinary Azents user messages in both Web presentation and model context.

## Non-Goals

- A shared Platform Slack App that asks users to select among accessible Agents.
- Explicit Slack-to-Azents account linking or automatic identity matching.
- Slack direct messages, message shortcuts, reaction triggers, or automatic invocation by trusted bots.
- Slack Connect shared channels in the first release.
- Implementing Discord, GitHub comment, Jira, or other provider adapters in the first release.
- Automatically forwarding ordinary Agent responses or Azents Web conversation to Slack.
- Treating every external resource as a permanently isolated Agent session.
- Supporting multiple simultaneously active channel work items within one Slack thread.
- Automatically resuming disconnected subscriptions or unfinished channel work after reconnection.

## Requirements

### REQ-1. Multiple external-channel connections

An Agent must support multiple independent external-channel connections, including multiple connections of the same provider type and connections from different provider types.

**Acceptance criteria**

- An Agent can have more than one Slack connection.
- Adding or removing one connection does not replace unrelated connections.
- Connection-specific credentials, availability, and operational state remain independent.
- The first release exposes Slack as the only usable provider without imposing a one-Agent-to-one-connection product limit.

### REQ-2. Dedicated Slack App setup

An Agent owner must be able to connect an Agent to a Slack App that the owner created and installed.

**Acceptance criteria**

- Azents provides sufficient guidance or configuration material for the owner to create the required Slack App.
- The owner can register the Slack App credentials with the intended Agent.
- Messages received through that dedicated app route directly to the connected Agent without an Agent-selection step.
- The connection exposes whether it is active, disconnected, or requires reconnection without revealing stored secrets.

### REQ-3. Mention-started Slack thread conversation

A Slack channel mention must start or resume an Agent conversation only within the addressed thread.

**Acceptance criteria**

- A first `@Agent` mention in an unlinked Slack thread starts the linking and authorization flow.
- An approved first mention creates an Agent session when no session is linked and links the Slack thread to it.
- Approved follow-up messages in a linked thread reach the same Agent session without another mention.
- Public and private Slack channels are eligible only when the connected App is an explicit member of the channel.
- Messages from channels where the App is not a member are not collected, linked, or answered.
- Unlinked general channel traffic is not collected.
- Messages created by the connected Agent app do not invoke the Agent again.
- Slack direct messages, shortcuts, and reaction triggers do not start conversations in this release.

### REQ-4. Complete attributed thread context

The Agent must receive the Slack conversation context needed to understand an approved request, independently from who is allowed to invoke it.

**Acceptance criteria**

- Initial linking includes the relevant thread root and prior replies available to the connection.
- Subsequent messages in the linked thread are added in order.
- Context-only messages that have not been released by an authorized invocation from the same external resource remain in bounded External Channel pending context and are not projected into the Agent session, Web conversation, model context, or compaction state.
- An Azents Web message, channel-work continuation, or activity from another external resource does not release pending external context.
- An authorized participant message from the same linked external resource promotes the retained pending messages through the triggering message into the Agent session in deterministic provider order.
- When pending context was truncated by its retention limits, the promoted external turn explicitly identifies that earlier external context was omitted.
- Human, app, and bot-authored messages can all appear in context.
- Each external message identifies its source connection, external conversation, author identity, author type, timestamp, and invocation authorization state.
- Messages from unapproved or blocked participants and bots are represented as context rather than executable instructions.

### REQ-5. Separate context visibility from invocation authority

Only approved human participants may start or continue Agent execution, while other visible thread participants may still contribute context.

**Acceptance criteria**

- An approved participant's eligible message can wake or continue the Agent.
- An unapproved participant's message does not independently wake or instruct the Agent.
- An unapproved participant's or bot's context-only message does not enter the Agent session until an authorized invocation from the same external resource releases the pending context.
- A blocked participant's message does not wake the Agent or produce an approval response.
- A bot-authored message does not independently wake the Agent in the first release.
- An approved participant may explicitly ask the Agent to inspect or act on information supplied by another participant or bot.

### REQ-6. External participant approval and blocking

Previously unknown Slack participants must require an explicit access decision before their requests reach the Agent.

**Acceptance criteria**

- The first eligible mention from an unknown participant produces an Azents approval entry point and holds the participant's request from Agent execution.
- The Agent-level policy determines whether approval may be performed by any Azents user who can converse with the Agent or only by an Agent administrator.
- An approver may grant access for only the current Agent session or for future conversations with the Agent by the same external workspace participant.
- Deny rejects the current request without permanently blocking future approval requests.
- Block suppresses future approval prompts and Agent reactions until explicitly removed.
- The external participant receiving access and the Azents user granting access remain separate identities; approval never links or impersonates their accounts.
- Session channel management exposes session-scoped access and revocation controls.
- Agent settings expose Agent-level approvals, revocations, and block management.
- Approval does not grant the Slack participant access to the Azents Web application.

### REQ-7. Explicit external communication

The Agent must communicate with Slack only through explicit channel communication actions.

**Acceptance criteria**

- Ordinary Agent response text is not automatically forwarded to Slack.
- Ordinary Azents Web conversation is not automatically forwarded to Slack.
- An inbound Slack message is visibly represented to the Agent as external-channel input.
- The Agent can explicitly send a conversational reply to the linked Slack thread.
- The Agent can explicitly finish an external request without sending a reply.
- The Agent can update external work progress without sending a new conversational reply.

### REQ-8. Channel-specific follow-up work

Each linked external conversation must be able to maintain its own current follow-up task list independently of the session's ordinary Todo list and other linked conversations.

**Acceptance criteria**

- A linked Slack thread has at most one active channel work item at a time.
- The active channel work item contains ordered tasks with pending, in-progress, or completed status.
- The Agent can send an initial or intermediate Slack reply while creating or updating the task list.
- The Agent can update the task list without sending a conversational Slack message.
- An approved message arriving while work is active joins the same channel work and allows the Agent to revise its tasks.
- Different linked external conversations in one Agent session maintain independent active work and task state.
- The ordinary session Todo list does not become the external conversation's progress source of truth.

### REQ-9. Slack progress visibility

Slack participants must be able to see the current unfinished work separately from conversational Agent replies.

**Acceptance criteria**

- Creating unfinished channel tasks creates one progress message in the linked Slack thread.
- Task changes update that existing progress message rather than posting a new progress message for every change.
- Conversational Agent replies remain separate Slack messages.
- Completing or clearing all tasks deletes the progress message.
- A later new work item creates a new progress message.
- Failure to project a progress update is visible to operators or managers and does not replace the durable Azents task state.

### REQ-10. Continuation until channel work completes

Unfinished channel work must keep the Agent eligible for continuation until the Agent explicitly completes or clears the task list.

**Acceptance criteria**

- Sending an intermediate Slack reply does not by itself complete channel work that still has unfinished tasks.
- A successfully completed run with unfinished channel tasks schedules further Agent execution.
- Unfinished channel work survives context compaction, worker handoff, process restart, and unrelated additional messages.
- Completing or clearing all tasks stops channel-work continuation.
- Explicitly choosing no reply without follow-up tasks stops channel-work continuation.
- An immediate reply with no unfinished tasks stops channel-work continuation.
- One completed linked conversation does not stop continuation required by another linked conversation in the same session.

### REQ-11. Reliable external event handling

Repeated, delayed, or concurrently received Slack events must not produce duplicate external messages, duplicate session links, or duplicate Agent invocation for the same accepted event.

**Acceptance criteria**

- Re-delivery of the same Slack event is recognized as the same inbound event.
- Thread messages retain a deterministic order when multiple events arrive close together.
- An event accepted before a temporary process or worker failure remains recoverable.
- External event acknowledgement does not depend on completing an Agent run within Slack's delivery window.
- Context-only messages and invocation-eligible messages retain their distinct wake behavior during recovery.

### REQ-12. Subscription disconnect

An authorized user must be able to terminate the live link between one external Slack thread and its Agent session without deleting historical conversation.

**Acceptance criteria**

- Disconnecting a linked thread stops future event delivery from that thread to the session.
- The Agent can no longer target the disconnected thread for new channel communication.
- Active channel work is ended and the temporary Slack progress message is deleted when the connection remains reachable.
- Imported Slack messages and Agent session history remain available in Azents and are marked as belonging to a disconnected external conversation.
- Slack source messages are not deleted.
- Access grants and block records are managed separately rather than silently deleted by thread disconnect.
- A later eligible mention may create a new live link and new channel work; the old work is not automatically resumed.
- External-channel bindings, pending context, channel work, and unresolved provider cleanup do not by themselves block an otherwise eligible Agent session archive.
- Archiving an Agent session immediately terminates every external-channel binding to that session, ends its active channel work, removes never-projected pending context, and fences further external invocation or channel action against the archived session.
- Provider cleanup attempted because of session archive does not delay or roll back the archive when Slack is unreachable or the outcome is unknown.
- Restoring an archived Agent session does not reactivate its terminated external-channel bindings, removed pending context, or ended channel work.

### REQ-13. Connection disconnect and external revocation

An Agent owner must be able to terminate an entire Slack App connection, and Azents must safely handle the app or credentials being revoked outside Azents.

**Acceptance criteria**

- Disconnecting the connection stops inbound events and outbound channel actions for every linked conversation using it.
- All active channel work under the connection is ended and Azents attempts to delete temporary progress messages before credentials are removed.
- Stored Slack credentials are removed from Azents when the owner disconnects the connection.
- Existing Agent sessions, imported messages, and work history remain available.
- Removing or revoking the app from Slack results in a disconnected or reconnect-required state rather than silent continued operation.
- Reconnecting credentials does not automatically restore old subscriptions or resume unfinished work.
- Any progress message that could not be deleted because the connection was already unavailable is surfaced for management or later cleanup.

### REQ-14. Web and external-channel continuity without leakage

Authorized Azents users must be able to view and continue a Slack-originated Agent session on the Web without making the Web a transparent relay to Slack.

**Acceptance criteria**

- A Slack-originated Agent session is available to Azents users who already have permission to access that Agent and session.
- Web input and ordinary Agent output stay within Azents unless the Agent explicitly invokes a channel communication action.
- External messages remain visibly attributed to their Slack origin in the Web conversation.
- Slack participant approval alone does not grant Web session access.

### REQ-15. Source-aware external-message presentation and lowering

External-channel messages must remain visibly and semantically distinct from ordinary Azents user-authored messages in both Web presentation and model input.

**Acceptance criteria**

- An external-channel message renders as a distinct compact, left-aligned source item rather than an ordinary human user-message bubble.
- The compact item identifies the provider, external conversation or resource, and external sender without requiring expansion.
- Expanding the item reveals the safe delivered message body, provider timestamp, author type, and invocation authorization state available to Azents.
- When the provider supplies a stable and validated original-message URL, the expanded item exposes an accessible action to open the original message in a new browser tab using safe external-link behavior.
- A missing, invalid, or unavailable original-message URL does not hide the message body or other source attribution and does not render a broken link.
- Live and durable projections of the same external message use one semantic identity so durable history replaces live state without duplicate or disappearing rows.
- Model lowering uses an explicit source-labeled envelope that identifies the external provider, conversation or resource, sender, message kind, authorization state, and safe body.
- Model lowering does not present external-channel content as undifferentiated direct human input from the current Azents Web user.
- Expansion state and other presentation-only preferences do not change canonical external-message content or model lowering.

## Fixed Constraints

- The first usable provider is a manually created per-Agent dedicated Slack App.
- The first release supports public and private Slack channels where the dedicated App is an explicit member and does not guarantee Slack Connect shared-channel behavior.
- App membership is the common boundary for receiving mentions and thread messages, reading available thread context, and publishing replies; the first release does not request permission to write into public channels where the App is not a member.
- The product model must not assume that one Agent has only one external connection.
- The product model must not assume that one Agent session can link only one external conversation or provider type.
- The product model must keep external connection authorization separate from linked-conversation state, external participant access, channel work, and Azents user identity.
- Agent output must fail closed against accidental external publication: only explicit channel actions may publish externally.
- External participant content, including approved participant content, is external input and must retain source attribution across execution and compaction.
- Pending external context is resource-scoped and bounded by age, message count, and normalized content size; Web input and unrelated external resources never release it.
- External-channel messages must preserve typed source provenance through durable events, Web projection, model lowering, and compaction even when a model provider requires a compatible generic message role.
- Original-provider links must be rendered only from validated provider-owned message URLs and must use safe external-link behavior.
- A disconnected external link is terminal for its active channel work and is never automatically resumed.
- Historical Azents conversation is retained when a connection or linked conversation is disconnected.
- Cleanup of a Slack progress message may be impossible after external credential revocation; the inability to perform external cleanup must not delete or falsify Azents history.
- External-channel activity is non-critical to Agent session archive admission; archive terminates the affected external-channel state instead of requiring a separate prior disconnect.

## Open Assumptions

- The precise Slack presentation of the approval entry point may be selected during design, but the approval decision and pending request must remain durable and recoverable.
- The precise Slack visual components used for the progress message may be selected during design as long as one mutable current-work message is presented and deleted on completion.
- The exact retention period and audit presentation for completed internal channel work will be selected during design; Slack progress messages are deleted at completion regardless.
- Channel work continuation uses the Agent session's existing successful-run continuation lifecycle rather than requiring an external wall-clock scheduler, unless feasibility validation finds a blocker.
- External provider rate limits may delay thread hydration or progress projection, but accepted inbound messages and durable work state must remain recoverable.
- The exact visual component may reuse the existing internal Agent-message collapsed presentation family, but the Design will define provider-specific source labels, detail fields, and responsive behavior.
- Original-message links are conditional on the provider exposing a stable permalink that Azents can validate for the associated connection and resource.
- The initial pending-context retention defaults are seven days, 100 messages, and 256 KiB of normalized body and metadata per external resource; the earliest limit wins and older content is removed with an explicit truncation marker.

## Confirmation

The initial Requirements, the source-aware external-message presentation and lowering amendment, the public/private Slack channel scope amendment, the bounded pending-context amendment, and the archive-triggered external disconnect amendment were confirmed by the requester on 2026-07-21 before the corresponding ADR decisions continued.
