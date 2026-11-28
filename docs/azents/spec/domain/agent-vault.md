---
title: "Agent Vault requests"
created: 2026-11-28
tags: [vault, agent, chat]
---

# Agent Vault requests

An admitted execution can call `vault_request` with a purpose and an ordered
list of distinct entry names and display labels. It cannot supply values or
select another Agent, Session, submitter, or deadline. Request creation does
not require a Runtime or suspend the execution.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Agent Vault storage](agent.md#vault-storage) owns the encrypted values.
- [Conversations and Sessions](conversation.md) own access to the original chat.
- [Session mailbox](../execution/mailbox.md) owns durable completion admission.
- [Session lifecycle](../execution/session-lifecycle.md) owns archive and purge.
- [External Channel delivery](../flow/external-channel-delivery.md) provides the
  provider transport and current route authority.

## State and access

`agent_vault_requests` is keyed by request ID and references the exact original
Session by `session_id` with cascade on purge. It stores the value-free request
specification, the database creation time and deadline, terminal settlement
and optional provider evidence. The nullable `button_label` stores external
input button text separately from destination authority. The unique
`anchor_event_id` is placement identity, not a foreign key: the open request
protects that history event from compacted-event retention, but normal
retention applies after settlement.
History and live delivery use the same event identity. Chat rereads request
state without rewriting the saved event. The card does not open an input
dialog on arrival. A click or explicit `vaultRequest` query on the canonical
Session path opens the same chat dialog after authentication.

The deadline is 24 elapsed hours after creation. An overdue open row is
effectively expired even before the scheduler persists that state. Team access
requires Workspace membership; a private User Session also requires its owner.
Neither chat access nor possession of the link confers Vault management.
Archive or Agent retirement denies submission. Restore does not extend the
deadline or reopen terminal rows.

Submission locks current Agent, Session lifecycle and request authority,
validates the entire named batch and checks elapsed database time. The same
transaction upserts encrypted values, settles the request, and admits one
typed `vault_request_completed` input with a wake-capable transition to the
original Session. This input carries request identity and ordinary mailbox
correlation, not human text or form values. Only a routing wake is sent after
commit. Expiry does not enqueue input or wake; replay is rejected even after
mailbox consumption.

## External status messages

An optional Discord or Slack destination is an explicit provider channel
currently connected and routable to the requesting Agent in its Workspace.
The scheduler claims one initial post and rechecks the exact binding before
sending. A Discord embed or Slack Block Kit message displays the Agent-authored
purpose and ordered field labels as text, not as links or mentions. Slack
includes the same context in its accessible fallback text. The only navigation
action is an input button, and no submitted value appears. The Agent may set
`button_label` for an explicit channel destination: one printable nonblank
plain-text line of at most 75 UTF-16 code units. Requests without a label show
`Enter values`; custom text does not change the dialog URL or terminal status.
The scheduler records only a confirmed delivery address and installation
identity. After settlement, it claims one best-effort edit to that exact
message under current
authority. The purpose and field labels stay visible while a link-free disabled
button on Discord or status text on Slack replaces the input action. A late receipt
can still enable the edit while the request is retained. Unknown creates,
failed edits, revocation, and purge do not cause a replay, fallback, or reopened
request.

## References

- [Request persistence and settlement](../../../../python/apps/azents/src/azents/repos/agent_vault_requests.py)
- [Provider claims and receipt boundary](../../../../python/apps/azents/src/azents/repos/vault_request_delivery.py)
- [Discord and Slack payload rendering](../../../../python/apps/azents/src/azents/services/vault_request_presentation.py)
