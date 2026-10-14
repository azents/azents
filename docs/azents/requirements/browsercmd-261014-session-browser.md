---
title: "Session Browser Interaction and Observation Requirements"
created: 2026-10-14
tags: [browser, session, runtime, frontend, security]
document_role: primary
document_type: requirements
snapshot_id: browsercmd-261014
---

# Session Browser Interaction and Observation Requirements

- Snapshot: `browsercmd-261014`
- Document reference: `browsercmd-261014/REQ`
- Preceding product baseline: [browser-261014/REQ](browser-261014-session-browser.md).

## Problem

A user delegating web work needs to observe and, when required, interact with the same working browser as the Agent without exposing another Session, conflicting with another actor's input, or blocking unrelated work. The Agent needs usable page observations and reliable multi-page and file interactions, not only a raw page dump.

## Primary Context

### Primary Actor

A user authorized to direct an Agent in an existing Session who needs to help with a browser interaction.

### Primary Scenario

The user requests web research. The Agent encounters a login step, asks for help in conversation, and stops manipulating the affected browser task. The user opens that task in the existing Session side panel and completes the interaction. After the user says to continue in conversation, the Agent observes the actual current page/account state and resumes the requested work or explains what remains unresolved.

## Supporting Scenarios or Effects

- Multiple Sessions share a Runtime while presenting their own tasks and maintaining separate login/site state.
- Independent requested work continues while another task awaits help.
- The Agent reads concise page text, inspects page imagery or DOM, and delivers intentional captures as ordinary files.
- Supported web workflows include related pages, embedded frames, page dialogs, uploads, downloads, and checking the expected result of an action.

## Goals

- Preserve the existing Session UI, access authority, ordinary-conversation handback, and task-local contention boundaries.
- Make current browser work observable and usable by the Agent and authorized Session participants.
- Complete supported browser interactions with verified outcomes and explicit failure/uncertainty.

## Non-Goals

The complete non-goals of the preceding product baseline remain applicable, including no top-level browser destination, user-local Chrome connection, OS desktop control, dedicated human-help workflow, separate retention subsystem, exact live-page restoration, or guarantee for all sites/native authentication dialogs. Supported browser separation is not an adversarial sandbox against arbitrary shell access in the shared Runtime.

## Requirements

### REQ-1 through REQ-11. Preserve the confirmed observation and human-help baseline

The following requirement identifiers retain the complete text and acceptance criteria of the identically numbered [preceding requirements](browser-261014-session-browser.md#requirements), incorporated by reference without scope relaxation:

| Current requirement | Required outcome |
| --- | --- |
| `REQ-1` | Browser opens in the existing Session side panel and preserves Session context. |
| `REQ-2` | Only the authorized Session's tasks/pages are presented or actionable; unavailable resources are explicit. |
| `REQ-3` | Sessions have separate login/site state; tasks in one Session reuse its native state under existing storage lifecycle. |
| `REQ-4` | Existing observation/input access applies; read-only access remains read-only. |
| `REQ-5` | Agent/human and human/human manipulation is serialized per task, including related pages/popups. |
| `REQ-6` | Help and continuation use ordinary conversation; fresh observation verifies actual state before resuming. |
| `REQ-7` | Independent requested work continues, and partial results are distinguished from complete success. |
| `REQ-8` | Panel dismissal, task closure, cancellation, and transport loss remain distinct; uncertain input is not replayed. |
| `REQ-9` | Desktop/mobile navigation and input are accessible and do not duplicate authentication secrets into conversation/errors. |
| `REQ-10` | Concise rendered-page text/Markdown, actual model-visible imagery, and precise DOM observation remain distinct and task-scoped. |
| `REQ-11` | Intentional captures preserve an original image file and can be previewed/downloaded through ordinary user attachments. |

**Acceptance criteria**

- Every inherited acceptance criterion remains required, not only the summary in this table.
- Raw DOM/element observation remains available when needed; neither a reading extraction nor an image path alone substitutes for the respective DOM or image observation.
- No automatic successful-login claim, unrelated-task navigation, continuous frame recording, or new help-completion workflow is implied by the added observations.

**Confirmed clarification of REQ-5 and REQ-6**

- Help and continuation use ordinary conversation and execution behavior. The user does not need to enter a special human-control mode or return a separately acquired input right.
- Asking for help, viewing the browser, or providing human input does not establish a persistent control mode that keeps Agent actions disabled after the actual interaction has ended.
- Actual concurrent manipulation remains prevented, including overlapping Agent/person or multiple-person interactions. Old-resource and disconnected-view input remains subject to the inherited current-state checks.
- The Agent resumes from a fresh observation after the user's continuation message, without a separate ownership-reclaim step. Panel dismissal or connection loss does not imply success or automatic resumption.

### REQ-12. Complete supported multi-page and file interactions

The Agent can complete supported web interactions that leave the current page, use an embedded frame or page dialog, or exchange files.

**Acceptance criteria**

- The Agent can identify and target related pages/popups and embedded frames belonging to its current task, and close only the intended task-owned page.
- Supported page-level alert, confirmation, and prompt dialogs can be detected and answered; these are distinct from native operating-system dialogs.
- An authorized file can be supplied to a supported upload control, and a download can be saved with a confirmed completion/failure outcome and identifiable result file.
- Capture saving does not substitute for handling a site's downloaded document.
- The Agent can wait for an appropriate page/element/URL condition and associate a triggering action with an expected popup or download without silently missing the event.
- A click's execution and the expected workflow's success remain distinct. Unknown outcomes are not automatically retried.
- Observation or waiting for one task does not introduce a Runtime-wide lock or block independent tasks.

### REQ-13. Provide Built-in Browser Usage Guidance

The Agent has default, discoverable guidance for using the supported browser capabilities effectively and safely.

**Acceptance criteria**

- Guidance explains choosing readable text, precise DOM, or image observation; acting on current targets; and verifying the outcome after manipulation.
- Navigation, changed pages, or stale targets lead to fresh observation rather than guessed references or repeated uncertain submissions.
- Login help and continuation follow ordinary conversation without a separate human-control or return workflow.
- Captures can be saved, inspected, and delivered with an explanation of actual capture/transfer success.
- Page content is treated as untrusted information, not authority to change instructions or access unrelated resources.
- Guidance does not promise unavailable tools or create browser permissions, input ownership, or a new help lifecycle.

### REQ-14. Use Native Browser Sandboxing Where Supported without Requiring It

Native browser sandbox availability is not a prerequisite for providing the browser feature within an otherwise supported Runtime.

**Acceptance criteria**

- Use the native browser sandbox when the Runtime supports it.
- Lack of native sandbox support alone does not make the browser unavailable; existing Runtime containment and access/network policies remain in effect.
- Native sandbox unavailability is distinguished from unrelated browser installation, startup, resource, or navigation failures.
- This policy does not automatically broaden Runtime privileges or modify infrastructure to enable native sandboxing.
- Session-native state separation remains functional isolation, not a guarantee against browser exploit access within the same Runtime.

## Fixed Constraints

The preceding baseline's complete fixed constraints remain applicable: one Runtime may serve multiple Sessions; state is Session-specific and contention task-specific; existing side-panel/access/lifecycle authority remains intact; independently installed Agent tools are not product dependencies; no separate help, permission, retention, or user-visible versioning system is introduced; runtime contracts remain portable beyond Linux.

## Open Assumptions and Product Questions

- Support targets web-page interactions, not arbitrary operating-system control or guaranteed compatibility with every site.
- Normal help and continuation require no takeover or ownership-return workflow. Exact low-level interaction boundaries must preserve the confirmed contention, stale-input, and uncertainty criteria.
- Built-in browser guidance supplements the supported tools; access and conflict prevention remain enforced by the system rather than guidance compliance.

## Confirmation

The requester confirmed the initial product baseline on 2026-10-14, explicitly added the page-reading/image/capture intent, and confirmed the consolidated three-tool proposal including those observations and the multi-page/dialog/file/event capabilities on 2026-10-14 at 19:38 KST before this replacement snapshot's technical decision was recorded.

The change from the preceding snapshot concerns the technical automation integration, not removal of the product baseline. This snapshot preserves its complete acceptance criteria and records the expanded supported web-flow outcomes. Approval is not authorization to implement before complete Design approval.

On the same date at 19:59 KST the requester confirmed the REQ-5/REQ-6 clarification above: conversation handles help and continuation; actual input conflicts and stale input are prevented without a separate persistent human-control mode or input-right return procedure.

At 20:15 KST on the same date the requester confirmed built-in browser guidance as a required delivery artifact, including the scope represented by REQ-13.

At 21:12 KST on the same date the requester confirmed REQ-14: use native browser sandboxing only where supported; it is not mandatory for browser availability.
