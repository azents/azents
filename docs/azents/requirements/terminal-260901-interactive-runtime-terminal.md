---
title: "Interactive Runtime Terminal Requirements"
created: 2026-09-01
updated: 2026-09-01
tags: [terminal, runtime, session, workspace, security]
document_role: primary
document_type: requirements
snapshot_id: terminal-260901
---

# Interactive Runtime Terminal Requirements

- Snapshot: `terminal-260901`
- Document reference: `terminal-260901/REQ`

## Problem

Users can operate an Agent Runtime indirectly through Agent tools and Workspace features, but they cannot open a real interactive terminal from a Chat Session. They need direct terminal access that behaves like a terminal, remains aligned with Session work, respects Runtime lifecycle and administrative policy, and does not expose a terminal where no managed Runtime exists.

The current Agent-level `shell_enabled` setting also overlaps with managed Runtime presence for Agent Runtime Toolkit availability. Browser Terminal permission is a separate product concern and must not inherit or reuse that setting.

## Primary Actor

A user who can access a Chat Session and its Agent, where the Agent has a managed Runtime and effective Terminal policy permits access.

## Primary Scenario

The user opens Terminal from a Chat Session. If the managed Runtime is stopped, the Terminal surface reports that state and waits for the user to explicitly start it. Once the Runtime is available, the user opens one interactive Terminal in the Session's working folder, runs interactive commands, moves between the supported docked and focused presentations without losing the terminal, briefly disconnects and reattaches to the same terminal, and explicitly terminates it when finished.

## Supporting Scenarios

- A mobile user opens the Session Terminal directly in a focused presentation, uses terminal-specific software key controls, and returns to Chat without terminating the PTY.
- A page reload or transient browser connection loss reattaches the same user to the same Session Terminal within a bounded grace period.
- A Runtime stop, restart, generation change, or Runner reconnect terminates affected Session Terminals and communicates that the previous terminal is no longer available.
- A System Administrator, Workspace manager, or Agent manager disables Terminal at the scope they control, and affected Terminal access is revoked without allowing a lower scope to restore it.
- A user opens a Runtime-free Agent and sees the ordinary Chat experience with no Terminal affordance or Terminal setup prompt.

## Goals

- Provide a real interactive terminal for a Chat Session's managed Agent Runtime.
- Keep terminal ownership, initial working context, reconnect behavior, and quotas aligned with the Chat Session.
- Provide responsive desktop and mobile Terminal experiences without replacing the existing Chat and Workspace surfaces.
- Make Terminal availability administratively reducible at Provider infrastructure Profile, Workspace Runtime Profile, and Agent settings levels.
- Remove `shell_enabled` without coupling its historical values or Agent Runtime Toolkit semantics to browser Terminal policy.
- Avoid durable storage of arbitrary terminal input and output while retaining sufficient metadata for operation and audit.

## Non-Goals

- Multiple named Terminals, Terminal tabs, or Terminal list management in the initial release.
- Durable terminal transcripts, command history synchronization, or later replay of terminal input/output.
- Preserving a PTY through Runtime stop, restart, generation change, Runner reconnect, or re-provisioning.
- Automatically starting a stopped Runtime merely because the user opened the Terminal surface.
- A separate per-user Terminal ACL beyond existing Chat Session and Agent access control.
- Terminal access, placeholders, or setup actions for Runtime-free Agents.
- Replacing or redesigning the Runtime's broader operating-system security boundary as part of this feature.

## Requirements

### REQ-1. Session-owned interactive Terminal

A qualifying Chat Session must provide a real interactive Terminal backed by its Agent's managed Runtime. The Terminal belongs to the Chat Session even though the Runtime and Agent Workspace belong to the Agent.

**Acceptance criteria**

- Opening Terminal creates or attaches to a PTY that accepts interactive input and renders ordered terminal output and control behavior.
- Terminals opened from different Chat Sessions are distinct even when those Sessions use the same Agent Runtime and Agent Workspace.
- The Terminal starts in the authoritative working folder bound to its Chat Session.
- A missing, pending, invalidated, or stale Session working-folder authority does not fall back to another directory.

### REQ-2. Explicit Runtime start

Opening Terminal against a stopped managed Runtime must not automatically start compute.

**Acceptance criteria**

- The Terminal surface clearly reports the stopped Runtime state and offers the existing authorized start action.
- No Runtime start request occurs until the user explicitly selects Start.
- After the Runtime becomes available, the Terminal can connect without requiring the user to leave the Chat Session.
- Runtime-free Agents do not show the Terminal surface or a start action for Terminal.

### REQ-3. Presentation continuity and explicit termination

Changing the Terminal presentation must preserve the same PTY, while explicit termination must end it.

**Acceptance criteria**

- Desktop supports `Collapsed`, `Docked`, and `Focused` Terminal presentation states.
- Mobile supports `Collapsed` and `Focused` states without a docked intermediate state.
- Collapsing, docking, focusing, or returning to Chat does not terminate or replace the PTY.
- An explicit terminate action ends the PTY and makes a later open create a new Terminal.
- Terminal presentation does not make the existing Chat and Workspace surfaces unavailable outside the focused Terminal state.

### REQ-4. Bounded browser reattachment

A transient browser disconnect or page reload must not immediately destroy active terminal work, but disconnected Terminals must not remain indefinitely.

**Acceptance criteria**

- Disconnecting the browser starts a bounded reattachment grace period.
- The same user reopening the same Chat Session within the grace period reattaches to the same Terminal.
- Another Chat Session does not attach to that Terminal.
- Expiration of the grace period terminates the PTY.
- Runtime stop, restart, generation change, or Runner reconnect terminates the PTY immediately rather than entering the browser reattachment grace period.

### REQ-5. Initial Terminal cardinality and future expansion

The initial release must allow at most one active Terminal per Chat Session while preserving a compatible path to multiple independently managed Session Terminals later.

**Acceptance criteria**

- A Chat Session cannot create a second active Terminal in the initial release.
- Reopening Terminal while one exists attaches to the existing Terminal rather than creating another.
- After explicit termination or terminal exit, the Session may create a new Terminal.
- The initial user experience contains no named-Terminal, tab, or Terminal-list controls.
- Adding multiple named Terminals later must not require redefining the ownership of existing Terminals or treating the Chat Session itself as the permanent Terminal identity.

### REQ-6. Hierarchical Terminal enablement

Browser Terminal availability must be independently controllable at the Provider infrastructure Profile, Workspace Runtime Profile, and Agent settings levels.

**Acceptance criteria**

- Existing and new Provider infrastructure Profiles permit Terminal by default.
- Existing and new Workspace Runtime Profiles inherit or preserve Terminal permission by default.
- Existing and new managed Agents permit Terminal by default.
- Disabling Terminal at any of the three levels makes effective Terminal availability false.
- A Workspace Runtime Profile cannot restore Terminal permission denied by its Provider infrastructure Profile.
- Agent settings cannot restore Terminal permission denied by either Profile level.
- Runtime-free Agents remain Terminal-ineligible regardless of stored policy values.
- User-facing management and status surfaces show the effective availability and the scope responsible for denial.

### REQ-7. Existing access control and active revocation

When effective Terminal policy permits access, Terminal use must follow existing Chat Session and Agent access control. Revoked authority must not remain usable through an already open Terminal.

**Acceptance criteria**

- A user who can access the Chat Session and its Agent can use that Session's Terminal without Agent-manager authority.
- Existing Public and Private Agent access boundaries remain authoritative.
- No separate per-user Terminal ACL is required.
- Disabling effective Terminal policy closes affected active Terminal connections and terminates their PTYs within a bounded revocation interval.
- Revoking a user's Chat Session or Agent access closes that user's affected active Terminal connection and terminates its PTY within the bounded interval.
- New Terminal opens and reattachment attempts are rejected as soon as the current authority is no longer valid.

### REQ-8. Independent removal of `shell_enabled`

The Agent-level `shell_enabled` product setting must be removed independently from browser Terminal policy. Managed Runtime presence must determine availability of the existing Agent Runtime Toolkit capabilities previously gated by that setting.

**Acceptance criteria**

- Agent create, update, read, and settings surfaces no longer expose `shell_enabled`.
- An Agent with a managed Runtime receives the existing Runtime-dependent Agent Toolkit capabilities without a separate Shell toggle.
- An Agent without a managed Runtime receives none of those Runtime-dependent capabilities.
- Historical `shell_enabled` values are not copied into Provider, Workspace, Agent, or effective Terminal policy.
- Removing a managed Runtime remains the way to remove the Agent's Runtime execution environment; changing Terminal policy affects human browser Terminal access only.

### REQ-9. Terminal privacy and metadata-only audit

Terminal input and output must remain ephemeral and must not become a durable transcript.

**Acceptance criteria**

- The product does not persist terminal input, output, screen contents, or command history for later replay.
- Operational and audit records may identify the user, Session, Agent, Runtime, Terminal lifecycle action, timestamps, outcome, and bounded usage measurements without recording terminal content.
- A browser reconnect can receive only the bounded live data needed to resume the current Terminal; it cannot retrieve a durable historical transcript.
- Normal service logs, traces, and error reports do not include terminal byte content.

### REQ-10. Mobile interaction

The Terminal must remain operable on mobile devices without requiring the desktop dock interaction.

**Acceptance criteria**

- Mobile opens Terminal from a compact launcher into a focused Terminal view.
- The focused mobile view provides clear return and terminate actions that cannot be confused with each other.
- Users can send common terminal control and navigation keys that are unavailable or inconvenient on a software keyboard.
- Keyboard visibility, viewport resizing, and orientation changes keep the usable terminal region visible and update terminal dimensions.

### REQ-11. Runtime lifecycle priority

The Agent Runtime lifecycle must remain authoritative over every Terminal lifecycle. A Terminal must never keep a Runtime alive or block, delay, or veto a Runtime lifecycle action.

**Acceptance criteria**

- Runtime stop, restart, reset, recreation, repair, and permanent removal remain available under their existing authorization and lifecycle guards regardless of active or reconnecting Terminals.
- Beginning an authoritative Runtime lifecycle transition invalidates affected Terminal attachments, replay grace, and PTYs without waiting for user confirmation in the Terminal.
- Terminal cleanup is bounded and cannot make an otherwise valid Runtime lifecycle transition fail or roll back.
- Terminal input, output, reconnect, and cleanup arriving after Runtime or Runner generation authority changes are rejected as stale.
- A Terminal never automatically starts or keeps running a stopped Runtime.
- Agent Workspace preservation or destruction continues to follow the selected Runtime lifecycle action rather than Terminal state.

## Fixed Constraints

- Runtime and Agent Workspace ownership remain Agent-scoped; Terminal ownership remains Chat Session-scoped.
- Runtime lifecycle authority is higher priority than Terminal lifecycle authority; Terminal state cannot retain or fence Runtime compute.
- Terminal filesystem authority uses the current Runner-reported Agent Workspace and the authoritative Session working-folder binding. No fixed Provider path or server-side fallback is allowed.
- Terminal authority is invalidated by Runtime desired-generation or Runner connection-generation changes.
- Effective Terminal permission is restrictive across Provider infrastructure Profile, Workspace Runtime Profile, and Agent settings.
- Browser Terminal policy and Agent Runtime Toolkit authority are independent.
- Terminal content is not durable product data.
- Initial Terminal count is one per Chat Session, but future multiple Terminal support must remain compatible with the initial ownership model.

## Open Assumptions

- The exact browser reattachment grace period, active-revocation interval, idle lifetime, maximum lifetime, connection limit, and byte-rate limits will be chosen during architecture decisions and design. Every value must be bounded and operationally configurable where appropriate.
- The initial Runtime implementation may support a platform-specific PTY backend, while the user-visible Terminal contract remains portable to future Runtime backends.
- A single user attachment is sufficient for the initial Terminal experience; concurrent multi-view attachment behavior will be resolved during architecture decisions without adding collaborative terminal scope.

## Confirmation

The initial Requirements snapshot was confirmed by the requester on 2026-09-01 before ADR and design decisions began. The Runtime-lifecycle-priority amendment in `REQ-11` was confirmed by the requester on 2026-09-01 before `terminal-260901/ADR-D5` and complete Design.
