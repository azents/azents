---
title: "External Channel Exchange File Publication"
created: 2026-07-25
tags: [slack, external-channel, exchange-file, delivery, architecture]
document_role: primary
document_type: adr
snapshot_id: slack-260725
---

# External Channel Exchange File Publication

- Snapshot: `slack-260725`
- Requirements: [`slack-260725/REQ`](../requirements/slack-260725-outbound-exchange-files.md)

## Context

The implemented `files-260723` snapshot limits outbound `channel_action.files` to
absolute Runtime paths. Its durable manifests are preflight metadata only, and delivery
streams Runtime ranges after commit. The same Agent can hold a user-visible Exchange file
URI from a generated output or `present_file`, but must first copy it into Runtime before
publication.

Exchange file execution access already has a canonical authority boundary:
`ExchangeFileService.resolve_for_authority()` validates the current workspace, Agent,
Session tree, run, and owner generation without inferring a User identity. This boundary
is appropriate for adding a second explicit outbound source form.

Observed Slack deliveries uploaded bytes successfully but received
`invalid_arguments` from `files.completeUploadExternal`. Slack's external upload flow
uses a form representation whose `files` value is a JSON string; the completion call
needs a request-specific encoding path while existing Slack message operations retain
JSON payloads.

## Decisions

### slack-260725/ADR-D1. Allow only Runtime paths and authority-resolved Exchange URIs as outbound sources

**Affects:** `slack-260725/REQ-1`, `slack-260725/REQ-2`,
`slack-260725/REQ-3`

Keep absolute Runtime paths as the existing source form. Add `exchange://` as the only
URI source form, resolved through `SessionResourceAuthority` before commit and again at
the actual provider upload. Durable manifests retain the original source reference,
bounded display metadata, expected size, and an explicit source kind; they never retain
file bytes.

`artifact://`, `azents://`, relative paths, and other schemes are not outbound source
forms. They remain usable only through their existing explicit materialization paths,
where applicable.

If an Exchange source cannot be reauthorized or its metadata or bytes no longer match
the committed manifest after commit, terminalize the delivery as failed before Slack
completion. The ordinary at-most-once provider behavior remains unchanged.

**Rejected:** Materializing every Exchange source into Runtime introduces an unnecessary
copy and makes publication depend on Runtime persistence. Treating every existing URI
resolver as an outbound source would weaken source review and conflate distinct
lifecycle/authority contracts. Persisting Exchange bytes or a private staging object
would add retention and cleanup behavior outside the confirmed scope.

### slack-260725/ADR-D2. Use form-encoded Slack completion with a serialized files collection

**Affects:** `slack-260725/REQ-4`

Send `files.completeUploadExternal` as form data with `files` serialized to a compact
JSON string, plus `channel_id`, `thread_ts`, and `initial_comment`. Keep JSON encoding
for `files.getUploadURLExternal` and ordinary Slack message operations.

The completion request still occurs exactly once after every upload succeeds, preserving
ordered file IDs, titles, root-thread targeting, and one combined delivery outcome.

**Rejected:** Keeping one generic JSON-only Slack request helper preserves the observed
provider rejection. Introducing a dedicated Slack SDK solely for one request would add a
new dependency and broader adapter surface without addressing the provider boundary more
narrowly.

## Risks

- Exchange resolution currently returns bounded complete bytes rather than a storage
  stream. The existing configured outbound limits bound this memory use.
- A provider-side behavioral change may still reject a valid completion request; the
  delivery ledger preserves that bounded error without claiming success.
