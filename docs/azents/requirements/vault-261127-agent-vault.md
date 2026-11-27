---
title: "Agent Vault Requirements"
created: 2026-11-27
updated: 2026-11-28
tags: [vault, agent, security]
document_role: primary
document_type: requirements
snapshot_id: vault-261127
---

# Agent Vault Requirements

- Snapshot: `vault-261127`
- Document reference: `vault-261127/REQ`

## Problem

Agent tasks that need credentials should not require users or agents to copy secret values into conversations or tool arguments. Existing environment settings supply values to commands whether or not the individual call needs them, and do not provide a task-initiated way to request missing values from a user.

## Primary Context

An Agent administrator or Workspace Owner sees a Vault request card in the Azents conversation for a portal account and password. They open the secret-entry dialog from the card and submit both values together. The Agent can use those entries by name in a browser action without turning the submitted values into conversation content.

## Supporting Scenarios

- An Agent saves a value already held in an accessible Runtime file, without reading the value into the model context.
- An Agent supplies an explicitly selected Vault value to a single CLI command.
- An Agent delivers an input request to a specified, authorized Discord or Slack channel.

## Goals and Non-Goals

- Provide an Agent-owned Vault with separate management and use paths.
- Keep plaintext out of the normal Vault registration and delivery records.
- No personal or cross-Agent shared Vault, automatic Runtime injection of Vault values, per-use approval, plaintext lookup tool, provider-native credential form, or general shell output filtering.
- No guarantee against disclosure by a command or site after it has received a value.

## Requirements

### REQ-1. Manage Agent-owned entries

- Each Agent has a Vault menu under its settings, separate from Runtime environment settings.
- Only a Workspace Owner or an administrator of the exact Agent can register, replace, or delete entries through the settings UI or submit values in a requested Azents form.
- Settings show entry names without returning stored values. The contributor label is informational and does not affect ownership, use, replacement, or deletion rights.
- A different Agent cannot use or manage an entry by reference, even when the same name is present in both Agents.

### REQ-2. Explicitly use entries in a tool call

- An eligible Agent execution, including one for a shared Agent, can designate a named entry in the call that consumes it. There is no separate lookup or approval step.
- For a command, the caller chooses the receiving environment variable. The value is supplied to that command and its process descendants; unrelated or later commands do not automatically inherit it. Existing general environment settings remain unchanged.
- For browser input, the caller designates the existing browser target field and the entry. The value is supplied to the field without routing it through a shell environment. Existing Session, browser target, and field access checks remain in effect.
- Missing, deleted, or unauthorized entries do not trigger a command or field input with a substituted value. Tool-managed results and errors do not return plaintext.

### REQ-3. Register a value from an Agent Runtime file

- An executing Agent can designate an accessible file and a destination entry in its own Vault. A user identity or a launch by a human manager is not required. This also applies to shared Agents.
- The tool does not require the model to read the file contents or put them in its arguments. The tool does not return the file contents.
- A missing or unreadable source does not create an entry. This capability does not authorize writes to another Agent's Vault or extend any human's settings permissions.

### REQ-4. Collect multiple values in Azents and close the request

- An Agent can request multiple named values together. The authenticated Azents form identifies the requesting Agent and supports submitting the requested fields together, including an account ID and password. A valid submission stores them in that Agent's Vault.
- When a channel is specified, Azents sends the input link to the exact authorized Discord or Slack destination; an unavailable or unauthorized destination is not silently replaced. Following the link opens the requesting Azents conversation and its shared secret-entry dialog for that request once access is verified. The chat retains the same request card and dialog used in web chat. Receiving or forwarding the link does not grant conversation or Vault management authority.
- Completion or timeout makes the request non-submittable. The channel request message is updated to show completion or expiration instead of the input link. A delivery update failure does not make the link valid again. A late or duplicate submission does not write values again.
- An unsubmitted request expires 24 elapsed hours after creation. The first release uses this fixed lifetime without a separate duration setting.
- Requesting values returns control to the Agent immediately. The Agent can end its turn or continue working; creating a request alone does not pause, stop, or hold the execution.
- When a request arrives in web chat, a standalone card appears in the conversation timeline with the purpose, requested field labels, and status. A new request does not open a dialog or take focus from the chat composer. Selecting the card's input action opens the shared secret-entry dialog; following the external channel's input link is also an explicit open action. The same card reflects completion or expiration and no longer offers input after the request closes.
- Successful submission delivers a value-free completion notice to the requesting Session's inbox and wakes that Session through normal input handling. An active Session can receive the notice without stopping or restarting its execution; an idle Session can act on it without a new human chat message.
- The external provider is not the input surface for the values. Channel status updates contain no submitted values.

### REQ-5. Keep plaintext out of normal product records

- With synthetic values and consumers that do not echo them, registration and use succeed without putting plaintext in chat, tool call arguments or tool-managed results, model requests, settings responses, or feature logs and errors.
- A normal tool invocation does not automatically persist the delivered value in a general Runtime file or environment configuration. This does not imply deletion of a file intentionally used as an import source.
- Ordinary stdout and stderr behavior stays unchanged. Contents printed by commands or shown by websites can still appear in ordinary output or observations.

## Open Product Decisions (Not Requirements)

- Whether expiration or cancellation also wakes the requesting Session. Success notification and wake are required.
- Whether a particular eligible submitter can be named or file import can explicitly replace existing entries. These details are not assumed as accepted scope.

## Confirmation

Confirmed by the requester on 2026-11-27 before architecture decisions began. Items listed under Open Product Decisions remain outside the confirmed requirements. This confirmation does not approve an implementation design.

The requester confirmed the fixed 24-hour lifetime in REQ-4 on 2026-11-28 (KST).
