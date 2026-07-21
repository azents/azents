---
title: "Scenario: On-call Agent"
tags: [architecture, engine, delegation, incident]
created: 2026-05-03
updated: 2026-05-03
implemented: 2026-05-03
document_role: supporting
document_type: supporting-supporting
migration_source: "docs/azents/design/agent-session-sandbox-scenarios/oncall-agent.md"
---

# Scenario: On-call Agent

## Scenario Summary

On-call agent resides in on-call channel. When alert fires, it creates a Slack thread per alert and writes summary, cause, impact, and recommended action items in that thread. Multiple alerts can fire simultaneously, so each alert needs independent raw session; but creating sandbox per alert would explode checkpoints and persisted artifacts.

## Requirement Analysis

### Functional Requirements

- Create Slack thread when alert is received.
- Spawn alert agent per alert and connect thread watch.
- Alert agent handles only that one alert/thread.
- Read-heavy diagnostics are handled by logs/metrics/traces/k8s read/deploy history API tools.
- Heavy/stateful/write work requiring sandbox is delegated to specialist agent.
- Same-day alert knowledge is recorded in IncidentLog/ShiftLog.
- Coordinator/manager agent reads ShiftLog and summarizes overall on-call situation.

### Non-functional Requirements

- Alert agent can be long-lived, so agent count must not be limited by concurrency.
- Resource limits are managed by run concurrency, external API rate, and specialist queue capacity.
- Do not create per-alert sandbox for alert agent.
- Do not use Team sandbox. Read-heavy work is sufficiently handled by API tools, and work requiring sandbox is heavy work, so specialist delegation is safer.

## Required Concepts

- Oncall Coordinator Agent
- Alert Agent Template
- Ephemeral Alert Agent
- Slack Thread Watch
- IncidentLog / ShiftLog
- Diagnostic API Tools
- Task Delegation
- Specialist Agent

## Technical Spec

### Coordinator policy

```yaml
agent_kind: persistent
role: oncall_coordinator
sandbox_policy: disabled
responsibilities:
  - alert intake
  - thread creation
  - alert agent spawn
  - shift summary
```

### Alert agent template

```yaml
template: oncall-alert-agent
spawn_mode: per_alert
sandbox_policy: disabled
run_concurrency: 1
capabilities:
  logs_query: true
  metrics_query: true
  traces_query: true
  k8s_read: true
  deploy_history: true
  shell: false
  filesystem: false
```

### IncidentLog / ShiftLog

```text
shift_id
alert_id
agent_id
service
severity
status
summary
suspected_cause
impact
recommended_actions
links
created_at
updated_at
```

### Delegation trigger

Alert agent delegates to specialist in these cases:

- write action required
- long script/file analysis required
- code modification/PR creation required
- strong credential or human approval required
- cannot resolve with diagnostic API tools

## Acceptance Criteria

- Even when multiple alerts arrive simultaneously, alert agents are created separately.
- Alert agent analyzes with read-heavy diagnostic API tools without sandbox.
- Per-alert tarball/checkpoint is not created.
- Heavy work moves to specialist delegation and original Slack thread origin is preserved. Source alert agent receives result, then explicitly calls Slack output tool to post in thread if needed.
- Daily on-call report can be created based on ShiftLog.
