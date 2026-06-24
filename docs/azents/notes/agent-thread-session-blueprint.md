---
title: "Agent Thread / Session Model Blueprint"
created: 2026-05-20
tags: [architecture, product, engine, memory]
---

# Agent Thread / Session Model Blueprint

This document is a blueprint that organizes nointern agent conversation/session model before implementation design. It is neither current system spec nor accepted ADR. When design becomes concrete later, relevant contents will be promoted to `design/`, `adr/`, or `spec/`.

## 1. Core Product Model

The basic conversation unit in nointern is **main work thread per agent**. This thread is not a simple chat room, but central point where agent remembers and performs assigned work.

Main thread is needed for these reasons:

- **Task assignment basis** — durable anchor is needed to define "this agent is doing this work."
- **Memory center** — reference point for agent to continue long-running work context and recent decisions.
- **Sandbox ownership** — if multiple independent sessions attach simultaneously to one agent's sandbox/work folder, they compete over same folder.
- **External channel integration** — related messages from multiple channels such as Slack, GitHub PR comment, Discord must converge into same work thread to feel like conversation with a person.

Example: after handling message from Slack channel A, if follow-up conversation for same work arrives from Slack channel B, agent must be able to answer B including A context. If sessions are separated per PR/channel, context breaks when one work is split across multiple external threads like stacked PR.

## 2. Reference Model for Compaction and Clear

Comparing OpenCode, Claude Code, Hermes, and OpenClaw, all compaction preserves meaning that "conversation continues," but storage method differs.

| System | Compaction handling | New session/thread? | Original history |
|---|---|---|---|
| OpenCode | Add compaction marker/summary to same session and use as prompt anchor | No | Preserved |
| Claude Code | Replace active context history with summary | Same session according to docs | Transcript preserved |
| Hermes | End SQLite session and create continuation session with parent_session_id | Yes, but continuation, not fresh | Old session preserved |
| OpenClaw | By default compaction in same transcript. Optional successor transcript | Optional | archive preserved |

What matters in nointern is not "whether physical row/id changes," but **whether logical conversation continuity perceived by user and agent remains intact**. If compaction rotates physical session, continuation lineage and handoff semantics like Hermes/OpenClaw are needed. If treated as simple fresh session creation, pending input, memory, sandbox ownership, and external thread routing all become unstable.

## 3. Parallel Coding Work

Problem: Coding agent is not limited to handling only one work item. User may expect it to research feature B while developing feature A, or handle N tasks concurrently.

Blueprint:

- Basic unit of parallelism is not "multiple sessions inside one agent" but **Agent team member**.
- Agent team is concept of quickly creating/deleting agents with same configuration based on agent template.
- If agent assigned to feature A needs research on feature B while working, create member agent in same team and assign feature B.

Benefits:

- Preserve `agent = main thread = sandbox owner` principle.
- Each team member has independent work context and sandbox policy.
- Result can be delivered to main/lead agent as handoff artifact.

Remaining design questions:

- What memory/context should be passed to new team member?
- Should result be absorbed into main thread as summary, or kept as artifact link?
- Should team member sandbox always be separate worktree, or allow read-only research agent?

## 4. Error Monitoring / Event Flood

Problem: Error notification Slack channel creates Slack thread per alert, and agent must quickly leave analysis result in each thread. However, processing every alert sequentially in one main session can be slow, while creating session/agent per alert can break shared operational context or increase sandbox cost.

Options considered:

- Process all events through main thread
  - Pros: context sharing is easy.
  - Cons: bottleneck, delay, and missed events risk during event flood.
- Create durable session per event
  - Pros: independent per-event processing is easy.
  - Cons: conflicts with 1 main thread per agent principle, and multiple sessions can attach to same sandbox.
- Create agent per event
  - Pros: 1 agent = 1 thread principle is preserved.
  - Cons: sandbox creation cost is high and shared monitoring context becomes weak.
- Run non-interactive ephemeral investigation per event
  - Pros: parallelize quick first analysis while preserving main thread continuity.
  - Cons: need design for how to explain "temporary session" to user and how to hand off follow-up.

Likely direction:

- When alert arrives, **ephemeral background investigation** quickly analyzes and leaves first response in external thread.
- Result is linked to main thread as typed artifact.
- User follow-up question is handled by main thread, receiving original alert/ephemeral result/external metadata together to continue answer.

## 5. UX Principles for Ephemeral Investigation

If user sees "temporary session was created," conversation can feel fragmented. Product terms below feel more natural than session.

- background investigation
- triage run
- probe
- incident analysis job

UX principles:

- Hide from default session list or keep as secondary detail.
- Show external thread response as "background investigation result."
- Allow raw trace with "View investigation details" when needed.
- Route follow-up to main thread, and leave investigation summary/artifact link in main thread.

Permission/sandbox principles:

- Ephemeral investigation uses read-only or isolated sandbox by default.
- If write work becomes necessary, promote to main thread or team member agent.
- Do not automatically reflect raw ephemeral transcript into memory. Link only important results as summary/artifact to main thread, and treat only repeated/important incidents as durable memory candidates.

## 6. Additional Use Cases to Consider

### 6.1 Urgent interrupt during long work

When main agent is coding for a long time, incident/security/operations question can arrive. Need routing policy based on urgency:

- put behind main queue
- answer first with ephemeral triage
- delegate to team member

### 6.2 Promotion from Ephemeral to Durable Task

If error alert analysis leads to actual code fix/PR, ephemeral should not directly modify sandbox. Instead:

- leave work proposal artifact in main thread, or
- create new team member agent and assign fix work.

### 6.3 Incident grouping / dedup

If only per-event ephemeral exists, alerts with same root cause can be analyzed repeatedly. Need grouping, throttle, and main thread incident summary accumulation based on channel/service/error fingerprint.

### 6.4 External thread follow-up routing

When follow-up question like "why?" arrives in Slack/GitHub thread, route to main thread, but must know which investigation the question is about. Need mapping that passes external thread id, original alert, ephemeral result id, and summary together.

### 6.5 Human approval / handoff

If ephemeral investigation proposes risky action such as deletion, restart, or deployment, it does not execute directly. Approval request and execution responsibility belongs to main thread or dedicated team member.

## 7. Temporary Conceptual Layers

Names are not finalized yet, but concept split before implementation design is as follows.

- **Agent** — subject of identity, config, memory policy, sandbox ownership.
- **Main thread / conversation** — durable anchor of ongoing work assigned to agent.
- **Run** — one model execution of main thread or background investigation.
- **Ephemeral investigation** — per-event non-interactive analysis work. Linked to main thread as result artifact.
- **Team** — coordination unit grouping multiple agents/members.
- **Handoff artifact** — typed summary/link that lets main thread absorb result from team member or ephemeral investigation.

Core principle:

> Persistent context seen by user attaches to agent main thread, and parallelism is solved by team member or ephemeral investigation. Compaction does not break main thread continuity.

## 8. Undecided Questions

- Should current nointern `AgentSession` be viewed as main thread as-is, or should upper concept such as `AgentThread` be added and `AgentSession` redefined as execution/history epoch?
- Should compaction be handled as event/projection inside same `AgentSession`, or create continuation session lineage?
- Should clear/new/reset mean preserving previous conversation as resumable and starting new main thread like Claude Code?
- What should retention period and searchability scope be for Ephemeral investigation transcript?
- By what criteria should ephemeral result be promoted into main thread memory?
