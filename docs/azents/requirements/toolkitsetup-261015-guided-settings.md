---
title: "Guided Toolkit Settings Requirements"
created: 2026-10-15
implemented: 2026-10-15
document_role: primary
document_type: requirements
snapshot_id: toolkitsetup-261015
tags: [toolkit, frontend, ux]
---

# Guided Toolkit Settings Requirements

- Snapshot: `toolkitsetup-261015`

## Problem and Primary Scenario

A Workspace manager or authorized Agent manager can complete the guided GitHub setup, but other Toolkit settings still present technical fields without a comparable explanation of prerequisites, setup order, verification limits, or final save effects. The requester asked to improve all Toolkit settings to the existing GitHub UX standard and deliver a PR autonomously.

## Requirements

### REQ-1. Understand and prepare each connection

Each user-configurable Toolkit explains its purpose, what information or access is needed, where to obtain it, and the next action. Instructions are specific to the provider and reflect supported connection methods. Existing GitHub and Google creation journeys remain usable and authoritative; internal/provider types must not become selectable solely because help content exists.

### REQ-2. Configure in a readable order

Settings use clear sections, nearby explanations, and a distinguishable final save action. Optional technical customization does not obscure normal setup. All existing configuration controls remain available, including saved credential replacement, connection tests, authorization, and Runtime constraints. The same experience works in standalone pages and Workspace/Agent dialogs.

### REQ-3. Verify and recover honestly

Connection tests and OAuth actions remain explicit. Explain what a test proves and what to check after a failure, without inventing access grants, live readiness, or changing persistence. Retain errors and user input. Saving configuration, testing a connection, and authorizing an account remain distinct actions.

### REQ-4. Review safely before saving

Present an understandable summary of the selected Toolkit, ownership, and user-selected operating settings before the existing explicit Add/Save action. Do not display secrets or credential-bearing URLs in a summary. Saved credentials remain unchanged unless the existing replacement controls are used.

### REQ-5. Accessible and localized presentation

New guidance and controls are available in all four existing locales, respect the product theme, and remain readable in light/dark modes and narrow dialogs. Add permanent component interaction/state coverage and representative assembled browser regression coverage.

## Fixed Constraints and Non-Goals

- Preserve server-owned availability, ownership, authorization, existing API schemas, secret storage, OAuth callback/resume paths, and current publication/cancellation boundaries.
- Do not create external accounts, grant permissions, introduce automatic tests, force new connection-test prerequisites, or broaden Runtime access.
- No new persistence, versioning, migration, deployment, or global theme redesign.
- Existing provider controls remain the source of configuration and credential behavior; this work improves their presentation rather than creating a competing setup system.

## Authorization

The requester directly authorized implementation across Toolkit settings on 2026-10-15, delegated in-scope UX decisions, requested no clarification questions, and requested a PR as the deliverable. This document records that instruction; it does not claim a separate document approval or authorize merging the new PR.
