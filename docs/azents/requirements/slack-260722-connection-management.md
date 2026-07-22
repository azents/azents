---
title: "Slack Connection Setup and Management Requirements"
created: 2026-07-22
updated: 2026-07-22
tags: [slack, external-channel, frontend, security, operations]
document_role: primary
document_type: requirements
snapshot_id: slack-260722
---

# Slack Connection Setup and Management Requirements

- Snapshot: `slack-260722`
- Document reference: `slack-260722/REQ`

## Problem

The first Slack External Channel management surface can leave a connection visible
after it has become disconnected while disabling the action that would remove it.
Connection recovery replaces only credentials, so an incorrectly entered Slack App
identity cannot be corrected. The setup dialog also exposes a callback path template
containing an unexplained `{selector}` instead of a usable URL, and it assumes the
owner already understands how to create and configure a Slack App.

An Agent administrator must never be trapped with an unremovable connection and
must be able to create or repair a Slack connection without prior Slack App
development experience.

## Primary Actor

An Agent administrator connecting a dedicated Slack App to an Azents Agent for the
first time.

## Primary Scenario

1. The administrator opens Slack connection setup for an Agent.
2. Azents explains both supported Slack App creation paths: using a generated App
   Manifest or configuring the App directly in Slack's UI.
3. The administrator follows either path without inventing a callback identifier,
   permission, event subscription, or credential mapping.
4. The administrator copies the Slack App ID, Bot User OAuth Token, and Signing
   Secret from the explicitly identified Slack screens and saves the connection.
5. Azents validates the connection and receives signed events through one documented
   callback URL.
6. If any value was entered incorrectly, the administrator edits the same connection
   and validates the replacement values.
7. At any time and in any connection state, the administrator can disconnect the
   connection immediately. It disappears from the active management list while
   already imported conversation history remains available.

## Supporting Scenarios

- An administrator prefers to configure every Slack setting manually rather than
  using an App Manifest.
- A connection is still configuring, degraded, missing credentials, awaiting
  reconnect, or already disconnected when removal is requested.
- A disconnect request is repeated because the first response was lost.
- An administrator changes the Slack App ID and credentials together after creating
  the wrong App.
- Home exposes the Slack callback publicly while all other Azents Web, Admin, health,
  and management routes remain private.

## Goals

- Make connection removal unconditional, immediate, and understandable.
- Make first-time Slack App creation self-contained inside the Azents setup flow.
- Let administrators correct connection identity and credentials without creating
  an undeletable replacement trail.
- Give Slack one stable callback URL whenever the provider protocol permits it.
- Preserve the existing narrow public-network boundary.

## Non-Goals

- Automatically creating or installing a Slack App through Slack OAuth.
- Publishing a shared platform Slack App.
- Exposing Azents management APIs through the public callback hostname.
- Restoring a disconnected connection's prior thread bindings or unfinished Channel
  Work.
- Recovering or displaying stored credential values after they have been submitted.

## Requirements

### REQ-1. Unconditional connection disconnect

An Agent administrator must be able to disconnect any managed connection immediately,
regardless of its current lifecycle or credential state.

**Acceptance criteria**

- The disconnect action is available for configuring, active, degraded,
  reconnect-required, missing-credential, and other visible connection states.
- Neither the Web UI nor the management service rejects disconnect because of the
  connection's current status.
- Repeating disconnect for the same connection is safe and produces the same terminal
  outcome.
- Credentials and inbound routing are disabled as part of the accepted disconnect.
- The disconnected connection no longer appears in the Agent's active connection
  management list.
- Historical provider messages and already projected AgentSession history are not
  deleted by connection disconnect.

### REQ-2. Editable incorrect connection

An Agent administrator must be able to replace an incorrectly configured Slack
connection's editable setup values.

**Acceptance criteria**

- The administrator can replace the Slack App ID, Bot Token, Signing Secret, and
  transport-specific App Token.
- Saving replacements validates the submitted App identity and credentials together.
- Existing secret values are never returned to the browser.
- Editing is available for every visible non-busy connection state.
- A failed edit leaves a clear recovery action and does not create an additional
  connection card.

### REQ-3. First-time Slack App guide

Slack setup must explain how to create and install a dedicated Slack App without
assuming prior Slack App development knowledge.

**Acceptance criteria**

- The guide contains a complete "Create from a manifest" path.
- The guide contains a complete "Create from scratch in Slack UI" path.
- Each path identifies the Slack menu names and the order in which the user visits
  them.
- The guide explains the difference between App ID, Bot User OAuth Token, Signing
  Secret, and App-Level Token.
- The guide identifies the exact Slack screen from which each required Azents value
  is copied.
- The guide explains Workspace installation, reinstallation after scope changes, and
  inviting the Bot to a target channel.

### REQ-4. Copy-ready Slack App Manifest

The setup surface must provide a complete JSON Slack App Manifest that can be copied
without manually filling provider configuration placeholders.

**Acceptance criteria**

- The Manifest includes Bot user configuration, required Bot scopes, subscribed Bot
  events, Socket Mode state, and the complete callback URL for HTTP setup.
- The Manifest contains no Bot Token, Signing Secret, App Token, or other credential.
- The administrator can copy the JSON with one action.
- The displayed Manifest remains available before a Slack connection exists.
- The UI does not present `{selector}` or another unexplained callback placeholder.

### REQ-5. Stable public callback

Slack HTTP callbacks should use one stable endpoint and provider payload identity
whenever the Slack protocol supplies enough identity to route and authenticate the
request safely.

**Acceptance criteria**

- Slack App setup uses one documented HTTPS callback URL instead of a per-connection
  URL when feasibility validation confirms safe payload routing.
- Ordinary callbacks are matched to the intended App installation before admission
  and are verified with that connection's Signing Secret.
- URL verification cannot invoke an Agent, admit an ordinary provider event, or
  mutate connection state.
- If one stable endpoint is technically infeasible, the implementation retains an
  opaque selector and the final delivery report records the concrete provider or
  security blocker.

### REQ-6. Narrow Home public routing

Home must expose only the required Slack callback operation on the public Azents
hostname.

**Acceptance criteria**

- The public hostname accepts only HTTPS `POST` for the exact supported callback
  path.
- Callback `GET`, path descendants, Azents root, health endpoints, management APIs,
  Web, and Admin remain unavailable through the public hostname.
- The existing private Azents routes remain unchanged.

## Fixed Constraints

- Disconnect admission has no lifecycle-status guard.
- Provider credentials and signing material are never exposed by API responses,
  logs, documentation examples, or test evidence.
- No legacy selector callback remains when the stable endpoint is feasible.
- Slack request signature verification remains mandatory for ordinary event
  admission.
- Already imported conversation and AgentSession history survives connection
  removal.
- Kubernetes and Home deployment changes are delivered through GitOps PRs.

## Open Assumptions

- Slack `event_callback` envelopes provide `api_app_id` and `team_id`, allowing an
  installation candidate to be selected before its Signing Secret verifies the raw
  request.
- A bounded URL-verification challenge may be acknowledged without connection
  admission because it creates no connection, event, Session, or Agent side effect.

## Confirmation

Confirmed by the requester on 2026-07-22 before ADR and design decisions began. The
requester explicitly required unconditional disconnect, editable incorrect
connections, both Manifest and manual Slack UI setup guides, a stable callback when
feasible, corresponding Home routing, PR delivery, and CI completion.
