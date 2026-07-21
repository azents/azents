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

- Short ID: `<word>-<YYMMDD>`

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

Add `implemented: YYYY-MM-DD` to frontmatter only after implementation is complete and verified. After that, do not modify the filename or content. Create a new Requirements snapshot for later changes and keep current behavior in living specs.
