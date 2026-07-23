---
title: "Slack Channel Control Feedback Design"
created: 2026-07-23
updated: 2026-07-23
implemented: 2026-07-23
tags: [slack, external-channel, frontend, backend, testenv]
document_role: primary
document_type: design
snapshot_id: slackops-260723
---

# Slack Channel Control Feedback Design

- Snapshot: `slackops-260723`
- Requirements: [`slackops-260723/REQ`](../requirements/slackops-260723-channel-control-feedback.md)
- ADR: [`slackops-260723/ADR`](../adr/slackops-260723-channel-control-feedback.md)

## Scope and Traceability

| Requirement | Decision | Mechanism |
| --- | --- | --- |
| `REQ-1` | `ADR-D1` | Shared bounded Slack block text normalizer used by admission and message normalization |
| `REQ-2` | `ADR-D5` | Full-ID metadata rows, approval provider-user projection, copy controls |
| `REQ-3` | `ADR-D3` | Management projection state plus ordered task presentation |
| `REQ-4` | `ADR-D2` | Decision-transaction delete intent and post-commit provider attempt |
| `REQ-5` | `ADR-D4` | Locked grant deletion and Mantine confirmation modals |
| `REQ-6` | `ADR-D5` | Wrapping approval header and cross-browser hidden tab scrollbar |

## Slack Block Normalization

A provider-specific helper traverses at most a bounded number of blocks and nested
elements. It accepts ordinary text objects and Slack rich-text containers. User and
channel elements become Slack reference syntax, while links, emoji, broadcasts, and
dates become deterministic readable text. Unknown elements contribute no text.

HTTP callback projection stores each accepted block as its type plus independently
bounded normalized text. Socket Mode uses the same callback projection. History
hydration can normalize the original provider blocks directly. Message normalization
prefers non-blank fallback text and otherwise joins the normalized block text.

## Approval Control Cleanup

The access decision service locks the access request and the original control-message
delivery. If that delivery is `delivered` and has a provider message key, the same
transaction creates one access-request-origin delete attempt containing only the
provider target and message key.

The management service receives the pending delete ID from every decision result and
passes it to the existing External Channel action delivery service after the decision
commit. Access-request delivery target resolution joins through the request route
rather than requiring a Session binding, so deny and block use the same path.

## Identity Projection

Managed approval data adds the provider user ID separately from the internal
principal ID. Slack control-message rendering receives the resolved label and provider
ID captured during ingestion. External-message details expose complete copyable
provider user, provider message, and correction revision identifiers.

## Activity Tracker Projection

Binding management loads the latest progress operation for the current work. A pure
projection helper produces `synchronized`, `missing`, `stale`, `delete_failed`,
`unknown`, or `none`. The web UI renders this state and each canonical task's title
and status. Revision values remain diagnostic metadata only.

## Grant Removal and Confirmations

Grant revocation reads and locks the owned row, snapshots the response value, deletes
the row, and commits. Existing external content has no grant ownership cascade.
External Channel destructive buttons use Mantine confirm modals with localized
confirm and cancel labels.

## Responsive Presentation

The approval header allows wrapping and prevents the status badge from shrinking.
The Session tab list keeps horizontal overflow while a CSS module hides Firefox and
WebKit scrollbar chrome.

## Test Strategy

### Verification matrix

| Behavior | Primary evidence | Boundary |
| --- | --- | --- |
| Signed Slack admission through approval and binding activation | Deterministic External Channel E2E | Existing credential-free fake provider and public API journey |
| Block-only text, bounded traversal, references, and edit identity | Slack HTTP/event unit tests | Direct payload variants are more deterministic than rebuilding the full E2E journey for every block form |
| Decision-time control deletion and grant removal | Access, management, repository, and delivery service tests | Tests create exact ledger outcomes, including failed and ambiguous provider results |
| Activity Tracker projection states and tasks | Management projection tests and Session Channels stories | All durable ledger combinations can be covered without provider timing |
| Complete identities and destructive confirmations | Component stories and TypeScript checks | Stories assert copyable full values and confirmation callbacks |
| Narrow-screen approval and Session navigation | Component rendering, CSS inspection, and web-surface regression E2E | Browser E2E remains a regression gate; Firefox and WebKit scrollbar rules are verified from the shared CSS module |

### E2E plan and fixture support

The existing deterministic Slack E2E remains the primary end-to-end regression for
connection setup, signed callback admission, unknown-participant approval, hydration,
and binding activation. The fake provider already accepts and records `chat.delete`
without retaining credentials or message text, so this feedback snapshot requires no
new fixture or seed. The focused service tests cover deletion outcomes and projection
states that would otherwise require timing-sensitive provider orchestration.

No live Slack credential or prerequisite snapshot is required. E2E evidence consists
of public API assertions plus the fake provider's sanitized operation counts,
delivery metadata, and Socket acknowledgements. Component evidence consists of
Storybook interaction assertions; code-quality evidence consists of Python and
TypeScript formatter, lint, type, and focused test results.

### CI policy

Focused Python and TypeScript checks run locally. Required PR CI, including
credential-free deterministic and web-surface E2E lanes, must pass. Optional live
Slack tests may skip only when they were not explicitly requested. Once live
credentials are supplied or live validation is requested, missing prerequisites or
test failures fail that run.
