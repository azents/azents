# Requirements Snapshot Template

Use this template after confirming one primary scenario. Keep the document solution-neutral and obtain explicit requester confirmation before creating an ADR.

```markdown
---
title: "<User-Visible Capability> Requirements"
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [<feature>, <product-area>]
---

# <User-Visible Capability> Requirements

- Snapshot: `<word>-<YYMMDD>`
- Document reference: `<word>-<YYMMDD>/REQ`

## Problem

<Describe the user pain or missing capability without proposing a solution.>

## Primary Actor

<Identify the main user or system actor.>

## Primary Scenario

<Describe one end-to-end scenario from trigger to observable outcome.>

## Supporting Scenarios

- <Secondary or supporting scenario, if any>

## Goals

- <Required outcome>

## Non-Goals

- <Explicitly excluded behavior or scope>

## Requirements

### REQ-1. <Requirement title>

<Write a solution-neutral user-visible requirement.>

**Acceptance criteria**

- <Observable pass condition>

### REQ-2. <Requirement title>

<Write another solution-neutral requirement.>

**Acceptance criteria**

- <Observable pass condition>

## Fixed Constraints

- <Compatibility, security, operational, or product constraint>

## Open Assumptions

- <Non-blocking assumption that remains explicit>

## Confirmation

Confirmed by the requester on YYYY-MM-DD before ADR and design decisions began.
```

Use `{word}-{YYMMDD}/REQ-N` when referencing an individual requirement from an ADR, design, implementation plan, or validation report.

Reuse the exact Requirements basename for the snapshot's primary ADR and Design. Do not create numbered ADR files; after migration, numbered ADR filenames and bare legacy ADR references are historical inputs only and belong only in explicit provenance or ambiguity records:

```text
docs/azents/requirements/<word>-<YYMMDD>-<slug>.md
docs/azents/adr/<word>-<YYMMDD>-<slug>.md
docs/azents/design/<word>-<YYMMDD>-<slug>.md
```

The filename date remains the KST Requirements creation date. ADR and Design frontmatter use their own actual `created` dates when those documents are created later.

Use `<snapshot>/ADR-DN` for accepted ADR decisions and `<snapshot>/DESIGN` for the primary Design. Supporting plans, audits, validation reports, and Specs do not use this basename rule.

Add `implemented: YYYY-MM-DD` to Requirements and Design frontmatter only after implementation is complete and verified. After that, do not modify the Requirements, accepted ADR, or Design. Create a new snapshot for later changes and keep current behavior in living specs.
