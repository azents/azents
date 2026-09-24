---
title: "Brave Search Native Toolkit Requirements"
created: 2026-09-25
tags: [agent, toolkit, search, image]
document_role: primary
document_type: requirements
snapshot_id: brave-260925
---

# Brave Search Native Toolkit Requirements

- Snapshot: `brave-260925`
- Document reference: `brave-260925/REQ`

## Problem

Agents cannot use a user-configured Brave Search API key through a native Azents Toolkit for independent search across relevant result types. Image discovery must also produce immediately visible results without requiring a separate agent action or managed Runtime.

## Primary Context

### Primary Actor

An Agent manager configuring Brave Search for an Agent and a participant asking that Agent to research or find images.

### Primary Scenario

The manager configures a Brave Search API key and enables the integration for an Agent. A participant asks for current information or images; the Agent selects the relevant search capability and returns attributable results. An image search shows bounded image results in the Azents conversation as part of the search result itself, without a second inspection or presentation step.

## Supporting Scenarios or Effects

- The Agent can search specialized news and video results as well as general Web results and model-ready Web context.
- A result includes usable image and source-page URLs for an Agent sharing a discovered image in a connected external channel.
- Agents with no managed Runtime can use the same search and image-display behavior.
- An Agent with image-input capability can visually inspect returned image content; one without that capability can still use textual result metadata without falsely claiming visual inspection.

## Goals

- Provide one native, API-key-backed Brave Search integration with a first-class set of search capabilities.
- Return trustworthy, bounded, source-attributable results, with images displayed to participants immediately on search.
- Work independently of managed Runtime while preserving the existing Toolkit access and credential protections.

## Non-Goals

- A separate image-inspection or image-presentation action for the ordinary image-search flow.
- Replacing model-provider-hosted Web search, general-purpose URL fetching, image generation, or a Brave-provided AI answer model.
- Specialized places, autosuggest, or spellcheck tools in the initial set.
- Automatically publishing search results to external channels without an Agent request to communicate there.

## Requirements

### REQ-1. Connect and control the integration

An authorized manager can configure a Brave Search API key using the existing Toolkit ownership and attachment choices, enable or disable it, replace the key, and identify connection failures without exposing the key in Agent output or UI read responses.

**Acceptance criteria**

- An enabled integration with a usable key is available to attached Agents; a disabled or disconnected integration exposes no executable Brave search operation.
- Workspace-shared and Agent-only ownership use their existing respective management boundaries.
- Entered keys are not returned in read responses or exposed as tool arguments, prompts, or tool outputs.

### REQ-2. Search across the agreed result types

The integration offers distinct, understandable searches for Web results, model-ready Web context, news, images, and videos. Search results retain usable source links and offer relevant language, region, recency, and result-size controls where the corresponding search type supports them.

**Acceptance criteria**

- An Agent can explicitly choose each of the five result types; news and images are not implicitly folded into general Web search.
- Results identify their source URLs and relevant titles or descriptions; invalid or exhausted credentials and provider errors are reported clearly without leaking secrets.

### REQ-3. Display image search results automatically

An image-search request itself delivers a bounded selection of resulting images to the participant in the Azents conversation, together with source attribution. The Agent does not need to call another tool to present the ordinary results.

**Acceptance criteria**

- Following one image-search action, the participant sees image previews/attachments in that action's result and can access the corresponding image and source-page locations.
- The same outcome is available for Agents that have no managed Runtime.
- A result that cannot be safely obtained as image content is identified as unavailable rather than silently represented as an attached image.

### REQ-4. Make image results usable by the Agent

The image-search result makes image content available to an Agent whose selected model supports image input, while giving a text-only model enough title, description, and URL information to communicate the result without claiming it visually inspected the image.

**Acceptance criteria**

- A vision-capable Agent can reason about an image returned by its search without a second tool call.
- A text-only Agent is told which image results it cannot visually inspect.
- Image content and context remain bounded for the selected model.

### REQ-5. Provide image URLs for connected-channel sharing

For every displayed image result, the Agent receives a usable image URL and source-page URL for use in a connected external channel message. The existing channel capability owns publication and presentation.

**Acceptance criteria**

- The Agent can include the image URL and source link in a channel message after searching, without a second image-search or presentation action.

### REQ-6. Keep existing execution boundaries

The integration is usable without managed Runtime and preserves ordinary Toolkit access boundaries, credential confidentiality, and bounded provider/network failures.

**Acceptance criteria**

- Web, context, news, image, and video searches run in both Runtime-enabled and Runtime-free Agents with equivalent result behavior.
- Requests to the external service do not reveal the key to the selected language model, browser, or end-user; timeouts, rate limiting, and malformed results fail safely.

## Fixed Constraints

- The integration is a user-configured native service Toolkit, not a provider-hosted `web_search` substitution.
- The ordinary image search result must itself display the images; no separate `present_file` or visual-inspection tool is required for the expected outcome.
- External channel publication is explicitly controlled by the Agent, not automatic merely because it searched.

## Open Assumptions

- The initial displayed image uses a bounded image representation; the requester has not specified a mandatory original-resolution image delivery policy.

## Confirmation

Confirmed by the requester on 2026-09-25 before ADR and Design decisions began.
