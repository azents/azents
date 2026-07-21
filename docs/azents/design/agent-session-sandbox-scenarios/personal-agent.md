---
title: "Scenario: Personal Agent"
tags: [architecture, engine, security, sandbox]
created: 2026-05-03
updated: 2026-05-03
implemented: 2026-05-03
document_role: supporting
document_type: supporting-supporting
migration_source: "docs/azents/design/agent-session-sandbox-scenarios/personal-agent.md"
---

# Scenario: Personal Agent

## Scenario Summary

Personal agent is a private agent for a specific user only. Only that user can talk to it, and Web raw session is exposed only to that user. In Slack, it communicates only through DM. It performs personal schedule, Slack message search, PPT creation, development, and automation work with user's delegated OAuth credential.

Personal agent creates skills together with user. Skill is a guide for performing work and is always referenced going forward.

## Requirement Analysis

### Functional Requirements

- Agent has `owner_user_id`.
- Only owner can access Web raw session, Slack DM, File API, skill, and delegated credential.
- In Slack, only DM watch is allowed.
- Use owner's delegated OAuth credential to use personal tools such as calendar, Slack search, Drive, GitHub.
- Skill list and body must be referable from DB, and system prompt plus `load_skill` must work without sandbox.
- If skill resource/template or file work is needed, create on-demand sandbox.

### Non-functional Requirements

- Private access policy must apply consistently to all entrypoints.
- Delegated credential use requires scope/consent/audit.
- Sync rules between DB snapshot of skill body and materialized copy in sandbox filesystem must be clear.
- Personal sandbox files are treated as owner private data.

## Required Concepts

- Private Agent / Owner User
- Access Policy
- Slack DM Watch
- Delegated Credential
- Skill DB Snapshot
- Skill Filesystem Materialization
- Dedicated On-demand Sandbox
- File Upload / Artifact Export

## Technical Spec

### Agent policy

```yaml
agent_kind: persistent
visibility: private
owner_user_id: required
sandbox_policy: on_demand
allowed_watches:
  slack_dm: true
  slack_channel: false
run_concurrency: 1
```

### Skill storage

DB has skill index and body snapshot.

```text
agent_id
skill_slug
name
description
body_md
source_path
manifest_root
content_hash
updated_at
synced_at
```

Sandbox filesystem has materialized copy and resources.

```text
/home/sandbox/.nointern/skills/{skill_slug}/SKILL.md
/home/sandbox/.nointern/skills/{skill_slug}/resources/*
```

### Sync timing

- FS -> DB sync on sandbox persist.
- FS -> DB sync on `reload_skill` tool call.
- FS -> DB sync on user's skill reload slash command.
- When skill is created/updated in DB, immediately materialize into active sandbox; for inactive sandbox, materialize on next restore/create.

### Delegated credential

```text
user_id
provider
scopes
encrypted_token
expires_at
refresh_token
consent_status
```

Tool execution verifies `agent.owner_user_id == credential.user_id`.

## Acceptance Criteria

- Non-owner user is denied access to Web/Slack/File API/skill/credential.
- Even without sandbox, skill list enters system prompt and `load_skill` returns DB body.
- Sandbox is restored/created when skill resource access is needed.
- Slack channel watch creation is rejected and only Slack DM watch is allowed.
