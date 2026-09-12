---
title: "Session Workspace Navigation Decisions"
created: 2026-09-12
tags: [frontend, session, architecture]
document_role: primary
document_type: adr
snapshot_id: panel-260912
---

# Session Workspace Navigation Decisions

Authority: confirmed [panel-260912 Requirements](../requirements/panel-260912-session-workspace.md).

## ADR-D1 — Preserve the session Chat mount and select supporting content

Accepted on 2026-09-12 for `panel-260912/REQ-1`, `REQ-2`, and `REQ-6`.
The concrete session route always renders the Chat entry. The existing `page`
query selects supporting content inside the session panel, including Context
detail links and Scheduled Task deep links. The session ID remains the Chat
mount identity. Closing the panel leaves the conversation mounted.

Replacing Chat with a separate feature page was rejected by the requester.
A second independent inspector route would retain the navigation inconsistency.
The main risk is resetting session state during a query transition; retain the
same entry type and session key and verify composer draft preservation.

## ADR-D2 — Responsive navigation around existing feature contents

Accepted on 2026-09-12 for `panel-260912/REQ-2` through `REQ-6`.
Desktop uses a vertical feature list beside existing content in a resizable
right panel. Mobile uses directly selectable horizontal tabs above full-width
content in the existing session content stage. Directional fades and buttons
represent actual remaining horizontal scroll.

The requester rejected a select, mobile side-by-side navigation/content, and a
second function-list/detail navigation stage. Individual feature interiors remain
unchanged. Existing workspace tabs become outer panel destinations; terminal
presentation is embedded in this panel while retaining terminal operations and
mobile software keys. Canvas remains a future extension, not a new editor.

Risk: tab overflow and hidden terminal sizing need browser verification.
Storybook must render actual components and providers, not copies of the mock.
