---
title: "Session Browser Observation and Input Requirements"
created: 2026-10-14
updated: 2026-10-14
tags: [browser, session, runtime, frontend, security]
document_role: primary
document_type: requirements
snapshot_id: browser-261014
---

# Session Browser Observation and Input Requirements

- Snapshot: `browser-261014`
- Document reference: `browser-261014/REQ`

## Problem

A user who delegates web work cannot reliably see the browser the Agent is using or complete a login interaction on the same working page. Help must not accidentally expose another Session's task, change another Session's account, or block unrelated work.

## Primary Context

### Primary Actor

A user authorized to direct an Agent in an existing Session who needs to help with a browser interaction.

### Primary Scenario

The user requests web research. The Agent encounters a login step, explains the needed help in conversation, and stops manipulating that browser task. The user opens the Session's browser in the existing Session side panel, completes the interaction, and says to continue in conversation. The Agent observes the current page and account state before continuing the original task or explaining that further help is needed.

## Supporting Scenarios or Effects

- The user observes ongoing browser work without being asked to distinguish Chrome processes or windows.
- Two Sessions use one Agent Runtime while presenting their own tasks and keeping login and site state separate.
- Independent, already-requested work can continue and produce partial results while one task needs help.
- Read-only Session access can observe without gaining interactive input authority.
- Desktop and mobile use the existing Session side-panel navigation and dismissal behavior.

## Goals

- Make the correct Session's current browser work observable and directly usable by authorized users.
- Prevent unintended cross-Session task exposure and account changes through the supported browser feature.
- Reuse ordinary conversation for help and continuation instead of introducing a separate human-task workflow.
- Preserve the existing Session UI, access authority, cancellation behavior, and unrelated execution.

## Non-Goals

- Connecting a user's local Chrome or controlling the entire operating-system desktop.
- A top-level Browser destination or a separate browser product page.
- Dedicated human-task registration, request cards, completion signals, return buttons, or request-expiry management.
- Requiring a particular browser automation protocol, vendor, process layout, or physical window separation.
- Hiding an account from other authorized participants in the same Session.
- Turning supported browser separation into an adversarial sandbox against arbitrary shell or raw browser-debugging access in the shared Runtime.
- Guaranteed support for all sites, CAPTCHA, passkeys, operating-system authentication dialogs, or native file pickers.
- Exact restoration of live page state, partially entered values, or in-flight page actions after Runtime replacement.
- A browser-specific backup, restore, retention scheduler, or state-reset product surface.

## Requirements

### REQ-1. Open the browser inside the existing Session side panel

The browser belongs to the existing Session side panel alongside its other destinations.

**Acceptance criteria**

- Opening Browser from Session A uses A's existing side panel, not a new top-level navigation destination or product page.
- Desktop and mobile reuse existing panel selection and close behavior.
- If a conversation provides a browser-opening action, it selects the Browser destination and exact task in the same Session's side panel; it does not signal task completion or continuation.
- Opening and closing the panel preserve the selected Session context.

### REQ-2. Present only the current Session's browser tasks

Supported browser observation and interactive actions are associated with the Session from which they were authorized.

**Acceptance criteria**

- A and B present their respective browser tasks and tabs, even while sharing one Runtime.
- Multiple tasks in one Session can be identified and their tabs distinguished.
- Using another Session's task or tab identity does not reveal its content or accept interactive actions.
- No tasks produces an empty state. A closed task produces a closed/unavailable indication rather than silently opening another task.
- Browser unavailability gives a reason rather than a blank surface pretending to be connected.

### REQ-3. Separate login and site state between Sessions

Each Session uses its own login and site state. Tasks within the same Session reuse that Session's state.

**Acceptance criteria**

- Logging in through A does not log B in.
- Logging out or switching accounts through A does not change B's login or site state.
- Tasks within A can reuse A's login state; within-Session account changes may affect those tasks and are not represented as task-level account isolation.
- This behavior does not require users to choose Chrome windows, processes, or debugging connections.
- Normal Run completion, panel dismissal, and ordinary Runtime stop/start do not deliberately erase the Session's browser state. Reuse follows the existing Runtime storage lifecycle, subject to the site's own login expiry.
- This natural reuse does not require additional browser-specific backup, restoration, retention, or cleanup work and does not promise reconstruction of live tabs or in-flight input.

### REQ-4. Apply existing observation and input authority

The browser follows existing Session and Agent access instead of introducing a separate browser permission system.

**Acceptance criteria**

- A person with existing access to a Session may observe that Session's browser work.
- A person authorized to direct the Agent in that Session may provide interactive input.
- Existing read-only Session access does not gain input authority.
- Unauthorized users do not receive page imagery or tab titles before authorization.
- Logged-in pages are shared with authorized Session participants and the Agent; no participant-private account guarantee is implied.

### REQ-5. Prevent conflicting input within one browser task

The Agent, a person, and multiple people cannot simultaneously manipulate the same browser task.

**Acceptance criteria**

- A competing input attempt is not executed while another actor is manipulating the same task, and the viewer can understand why input is unavailable.
- The input restriction covers the related pages and popups of that task without becoming a Runtime-wide or Session-wide lock.
- Input and viewing remain subject to current access and current task identity after reconnection or resource replacement.
- Preventing input conflicts does not require a dedicated human-help request or return workflow.

### REQ-6. Request help and continue through ordinary conversation

The Agent explains required human help and stops the affected browser manipulation using the ordinary conversation and execution flow.

**Acceptance criteria**

- The Agent can ask for login help in a normal message, and the user can open the browser and complete it without accepting a dedicated request card.
- A normal user message such as "I logged in; continue" provides the continuation context; no browser-return button or request-completion tool is required.
- The Agent observes the current task, page, and account state before continuing and does not treat the user's statement or panel close as proof of login success.
- If the condition remains unresolved, the Agent explains the problem and further help in conversation.
- Passwords and authentication codes are entered in the browser, not requested as conversation messages.

### REQ-7. Continue independent work and distinguish partial results

Already-requested work that does not depend on the blocked browser interaction may continue.

**Acceptance criteria**

- Waiting for help, human input, or closing A's task does not block or close B's task or an independent task in A.
- Login-dependent work or work affected by the same Session's account switch is not classified as independent.
- Finished partial results are delivered with an explicit explanation of the remaining work; the complete request is not falsely marked finished.
- If no independent requested work remains, the Agent waits for normal user input and does not invent additional work.

### REQ-8. Distinguish panel dismissal, task closure, cancellation, and transport loss

Existing conversation cancellation and Session controls remain authoritative. Browser presentation does not invent new help-request lifecycle controls.

**Acceptance criteria**

- Dismissing the side panel closes the viewing surface, not the remote tabs or Agent task.
- Explicitly closing a task's tabs affects that task, not other tasks or Sessions.
- Task cancellation and execution stop use existing product behavior; retained pages do not implicitly restart canceled work.
- A disconnected viewer is told that its frame is stale and cannot send input until current state is established.
- Uncertain clicks or submissions are not automatically replayed after reconnection.
- Connection loss, panel dismissal, or a stale browser-opening action is not interpreted as successful completion or a conversation instruction to continue.

### REQ-9. Provide accessible and content-safe observation and input

The Session browser should be usable through existing desktop/mobile navigation without duplicating sensitive page input into conversation or generic error surfaces.

**Acceptance criteria**

- Panel navigation, task selection, close actions, and focus transitions are keyboard accessible and convey connection/input state beyond color alone.
- Mobile panel dismissal returns to conversation in the same Session, and Korean composition input is not duplicated or submitted prematurely.
- Passwords, authentication codes, cookies, and sensitive full URLs are not copied to conversation or generic errors.
- Browser display and input remain in the Agent execution environment; no additional raw debugging endpoint or public Runtime ingress is a product requirement.

### REQ-10. Observe Pages as Concise Text, Images, and Structured DOM

The Agent can choose a concise readable text/Markdown glance, a rendered page image, or DOM-level observation appropriate to the task. Raw DOM alone is not sufficient for the initial browser surface.

**Acceptance criteria**

- A glance presents the current rendered page's relevant readable content in a concise text/Markdown form rather than requiring a full raw DOM dump.
- The glance makes its page/source and any bounded or partial extraction clear so omitted content is not represented as absent from the page.
- The Agent can actually receive and inspect the rendered page image; a text response containing only an image path is not sufficient.
- DOM/element observation remains available for precise page interaction and must not be confused with a main-content reading extraction.
- These observations are scoped to the Agent's current authorized Session/task and do not navigate or submit unrelated work merely to obtain a view.

### REQ-11. Save and Share Page Captures as Image Files

An intentional page capture can be saved as an image file and delivered to the user as an ordinary file attachment.

**Acceptance criteria**

- The Agent can save a capture of the current task's page as a Runtime image file with an identifiable source task and capture dimensions.
- The saved capture can be attached through the existing user file-delivery surface so the user can preview and download it.
- Model-image preparation and user-file delivery do not replace the preserved capture with an unintended re-encoded approximation.
- Capture and delivery distinguish success, unsupported/unavailable capture, and failed file transfer; a path alone is not proof the user received a file.
- Intentional capture/export does not imply persisting every live viewer frame or replaying browser input into conversation.

## Fixed Constraints

- One Agent Runtime can support multiple Sessions; this feature does not require separate Runtimes.
- Browser state is Session-specific, while browser input contention is task-specific.
- Preserve existing Session side-panel layout/navigation, existing access authorities, and ordinary conversation continuation.
- Tools independently installed by an Agent in its Runtime are not existing Azents product capabilities or implementation options for this feature.
- Browser state follows existing Session and Runtime lifecycle authority; do not introduce a separate retention contract or persistence subsystem.
- Do not add a human-task workflow, a second browser-only permission system, or user-visible version management.
- Keep runtime behavior portable to future non-Linux backends; operating-system desktop control is not part of this feature.

## Open Assumptions

- The initial supported interactions are web-page observation and input, not native desktop dialogs.
- A browser-opening action in a tool-result presentation is an allowed convenience, not authority to introduce a separate user request or permission workflow.
- Product behavior approval and local feasibility experiments do not establish production browser authorization, external transport, account isolation, or mobile input correctness.

## Confirmation

Confirmed by the requester on 2026-10-14 before ADR and implementation Design decisions began. Confirmation includes the existing Session side-panel scope, Session-specific task and login state, existing access authority, ordinary conversation help and continuation, task-local input conflict prevention, exclusion of Agent-installed tools as product options, and natural browser-state reuse under existing lifecycle behavior without separate retention or restoration work.

On the same date the requester explicitly added concise text/Markdown glance observation, Agent-visible page images, DOM-level observation, and capture-to-file/user attachment intent. REQ-10 and REQ-11 represent those additions. The complete updated criteria will be presented with the revised automation integration proposal for confirmation before accepting its new implementation mechanisms.
