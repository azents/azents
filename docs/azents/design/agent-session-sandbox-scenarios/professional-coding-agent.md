---
title: "Scenario: Professional Coding Agent"
tags: [architecture, engine, sandbox]
created: 2026-05-03
updated: 2026-05-03
implemented: 2026-05-03
---

# Scenario: Professional Coding Agent

## Scenario Summary

Professional coding agent has broad coding knowledge for a specific product or code area. It performs multiple coding tasks continuously on one long raw session, receives work through Jira ticket assignment, and watches Slack/GitHub/Jira feedback. User can directly enter Web raw session and pair program.

Multiple coding agents can exist by domain, and each is treated as one IC.

## Requirement Analysis

### Functional Requirements

- Agent has long-term identity by product/area.
- Agent maintains one long raw session.
- Web UI directly connects to raw session and supports pair programming.
- Jira ticket assignment, GitHub issue/PR comment/review, and Slack thread feedback are received as watches.
- In one agent workspace, git checkout, branch, test/build cache, and temporary artifacts are maintained.
- Commits/PRs/comments made by agent must be traceable as agent IC identity.
- Heavy coding work runs in same agent's dedicated sandbox.

### Non-functional Requirements

- Sandbox restore can be slow, so coding agent defaults to `on_demand`, but implementation details can separately use prewarm/keep-warm operational optimization.
- Workspace is maintained long-term and persisted with S3 checkpoint, not EFS.
- Git workspace is stored as tarball checkpoint, not object-per-file.
- Runs of same agent are serialized to prevent workspace race.

## Required Concepts

- Persistent Agent
- Raw Session
- Dedicated Sandbox
- External Watch: Jira, GitHub, Slack
- Event Origin / Reply Routing
- Agent Queue / Lock
- S3 Sandbox Checkpoint
- Agent Identity: git author, GitHub/Jira/Slack display identity

## Technical Spec

### Agent policy

```yaml
agent_kind: persistent
sandbox_policy: on_demand
access_scope: workspace_or_team
run_concurrency: 1
```

### Watch model

```text
GitHub PR/issue -> agent_id
Jira ticket -> agent_id
Slack thread -> agent_id
```

All watch events include origin metadata.

```json
{
  "source": "github",
  "repo": "azents/azents",
  "kind": "pr_comment",
  "number": 123,
  "comment_id": 456
}
```

### Sandbox persist

- In active state, `/home/sandbox` is canonical.
- On idle/hibernate, bundle `/home/sandbox` into tarball and store in S3.
- On restore, unpack S3 checkpoint.
- File API accesses through active sandbox; in hibernated state, access after restore.

### Output target

- To post to GitHub, agent explicitly calls GitHub comment/review output tool.
- To post to Slack, agent explicitly calls Slack thread output tool.
- UI streaming for Web input is handled by raw session transport.

During multi-turn work, which external channel receives a message is not decided by automatic "reply" routing, but by target of that output tool call.

## Acceptance Criteria

- One coding agent can have multiple Jira/GitHub/Slack watches simultaneously.
- User can open same raw session on Web and pair with agent.
- After creating file in sandbox, same file is restored after persist/restore.
- Even when concurrent events arrive for same agent, runs are serialized.
