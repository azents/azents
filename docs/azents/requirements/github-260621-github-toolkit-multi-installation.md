---
title: "GitHub Toolkit Multi-Installation Routing Historical Requirements Reconstruction"
created: 2026-06-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: github-260621
historical_reconstruction: true
migration_source: "docs/azents/adr/0069-github-toolkit-multi-installation.md"
---

# GitHub Toolkit Multi-Installation Routing Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `github-260621`
- Source: `docs/azents/adr/github-260621-github-toolkit-multi-installation.md`
- Historical source date basis: `2026-06-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

GitHub App credentials in the GitHub Toolkit previously selected one installation. That was enough when an agent worked in one organization, but coding agents often need to work across repositories owned by different organizations, such as `azents/*` and `hardtack/*`, in the same runtime session.

A GitHub App installation token is scoped to one GitHub App installation. It cannot access repositories outside that installation's account and repository selection. Therefore a single `GH_TOKEN` or a single MCP bearer token cannot represent multiple organization installations at once.

GitHub App installation metadata can be resolved from App credentials and an installation ID by calling GitHub's installation endpoint. Platform App OAuth already returns user-accessible installations with account login metadata, which Azents stores in `github_user_installations` for ownership checks.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
