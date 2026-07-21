---
title: "Generalized Sandbox Credential Injection — First Application with EnvVarToolkit Historical Requirements Reconstruction"
created: 2026-04-21
implemented: 2026-04-24
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sandbox-260421
historical_reconstruction: true
migration_source: "docs/azents/design/sandbox-credential-injection-2026-04-24.md"
---

# Generalized Sandbox Credential Injection — First Application with EnvVarToolkit Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sandbox-260421`
- Source: `docs/azents/design/sandbox-260421-sandbox-credential-injection-2026.md`
- Historical source date basis: `2026-04-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Build a generalized framework for delivering credentials to shell tools executed inside Sandbox. Complete isolation is assumed impossible; practical defenses are **short-lived TTL + egress allowlist + audit**.

First target is **EnvVarToolkit** — a general-purpose tool where workspace manager registers arbitrary environment variables (API key, token, etc.), and they are injected into child process env when `shell()` executes in agent session. This establishes toolkit state machine and `shell()` env injection path together, and later can extend dynamic renew paths such as GitHub installation token.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

**EnvVarToolkit usage flow** (workspace manager):
1. UI `/w/[handle]/toolkits/new` → select "Environment variables" type
2. enter name "My Notion Creds", add entry: `NOTION_TOKEN=secret_xxx`
3. confirm Warning modal (acknowledge leakage risk)
4. Save Toolkit → bind that toolkit from agent edit screen

**shell execution in agent session** (LLM):
1. Agent calls `shell_execute_code(command="curl -H 'Authorization: Bearer $NOTION_TOKEN' https://api.notion.com/v1/users/me")`
2. shell tool collects `expose_env()` result from active toolkits → passes as env to sandbox daemon
3. Child process env inside Sandbox has `NOTION_TOKEN`, curl succeeds

**Token rotation/delete** (manager):
- Overwrite Entry value → new value applies from next shell call (state machine reflects immediately)
- Delete Toolkit → injection into agent stops

## Supporting Scenarios

**EnvVarToolkit usage flow** (workspace manager):
1. UI `/w/[handle]/toolkits/new` → select "Environment variables" type
2. enter name "My Notion Creds", add entry: `NOTION_TOKEN=secret_xxx`
3. confirm Warning modal (acknowledge leakage risk)
4. Save Toolkit → bind that toolkit from agent edit screen

**shell execution in agent session** (LLM):
1. Agent calls `shell_execute_code(command="curl -H 'Authorization: Bearer $NOTION_TOKEN' https://api.notion.com/v1/users/me")`
2. shell tool collects `expose_env()` result from active toolkits → passes as env to sandbox daemon
3. Child process env inside Sandbox has `NOTION_TOKEN`, curl succeeds

**Token rotation/delete** (manager):
- Overwrite Entry value → new value applies from next shell call (state machine reflects immediately)
- Delete Toolkit → injection into agent stops

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
