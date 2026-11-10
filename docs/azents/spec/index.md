---
title: "Azents Spec Wiki"
created: 2026-11-04
tags: [documentation, wiki]
---
# Azents Spec Wiki

This is the connected current-system Spec, not a summary alongside another Spec.
Pages are organized around ownership and behavior: Session identity is distinct
from Run state, a model choice is distinct from its catalog, and a connection is
distinct from the tools it exposes. Start with a question and follow the links.
See [AGENTS.md](AGENTS.md) for how Agents ingest, query and lint this wiki.

## Follow the system

### From a message to durable work

[Conversations](domain/conversation.md) establish Session identity and visibility.
[Mailbox admission](execution/mailbox.md) turns authorized input into ordered work;
[Runs](execution/runs.md) own execution state, and the [Agent loop](flow/agent-execution-loop.md)
performs model/tool iteration. [Events](execution/transcript.md) record what happened.
[Actions](execution/actions.md) are durable operations, not a second transcript.
[Subagents](execution/subagents.md) are participants with their own execution Sessions,
not persistent Agent configurations. [Recovery](flow/run-resume.md) resumes durable work;
[compaction](flow/context-compaction.md) preserves usable context.

### Three different ways to continue

A [Goal](automation/goals.md) tracks an explicitly requested objective; a Todo list
organizes tasks without becoming execution authority. A [Routine](domain/routine.md)
asks whether useful work is warranted. A [Scheduled Task](domain/scheduled-task.md)
requires work and a terminal result for an admitted scheduled occurrence. Shared
[periodic infrastructure](flow/periodic-execution.md) admits work but does not merge
these contracts. Finishing one occurrence is not the same as finishing a Run, Goal
or [Channel Work](flow/external-channel-delivery.md).

### Configuration is not execution authority

[Agent configuration](domain/agent.md) owns the persistent Agent. The [catalog](domain/model-catalog.md)
describes available models; [selection](models/selection.md) freezes candidates and
operation snapshots. [Request capability admission](models/request-capabilities.md)
validates actual encoded requests. [Runtime profiles](runtime/profiles.md) select
managed compute, not model inference profiles. [Inference authority](domain/inference-authority.md)
and the independent [Proxy](domain/inference-proxy.md) do not replace the Worker's
normal inference path.

### Connections are not tool implementations

[Toolkits](domain/toolkit.md) define owned connections and mounting. [Personal connections](tools/personal-connections.md)
carry additional User-root constraints; [GitHub](tools/github.md), [Google](domain/google-connection.md)
and [MCP OAuth](flow/mcp-oauth.md) have their own identity contracts. [Discovery](tools/discovery.md)
controls model-visible definitions, [Toolkit State](execution/tool-state.md) controls
private state, and [runtime execution](tools/runtime-execution.md) controls actual
execution/network effects. [Instructions and Skills](tools/instructions.md) provide
context without inventing new resource authority.

### Physical resources and their owners

[Providers](domain/runtime-provider.md) host compute; [Runtime control](flow/agent-runtime-control.md)
authenticates Runner operations, and [persistence](flow/agent-runtime-persistence.md)
owns Workspace durability. [Projects and worktrees](runtime/projects.md) determine
Session working context, while [files](flow/file-exchange-storage.md), [terminals](runtime/terminal.md)
and the [Browser](flow/session-browser.md) have separate resource lifecycles.
[Session archive and purge](execution/session-lifecycle.md) and [Agent deletion](domain/agent-deletion.md)
coordinate cleanup without confusing registry removal with physical deletion.

### Slack and Discord end to end

[External Channels](domain/external-channel.md) define connections, routes and bindings.
Follow [ingress](flow/external-channel-provider-ingress.md) → [authorization](flow/external-channel-authorization.md)
→ [mailbox](execution/mailbox.md) → [execution](flow/agent-execution-loop.md)
→ [explicit delivery](flow/external-channel-delivery.md). [Channel lifecycle](flow/external-channel-lifecycle.md)
connects disconnect, archive, restore and purge to the owning Session and Agent.

## Identity and persistent configuration

- [Users and authentication](domain/user-auth.md) — signup, login, elevation and instance administrators.
- [Workspaces and membership](domain/workspace.md) — collaboration, roles, invitations and ownership transfer.
- [Agent configuration](domain/agent.md) — persistent Agent identity, management and configuration interface.
- [System Settings](domain/system-settings.md) — instance-wide operator and retention policies.

## Execution, context and lifecycle

- [Conversations and Sessions](domain/conversation.md) — public identity, participant visibility and Session APIs.
- [Session mailbox](execution/mailbox.md) — input envelopes, wake scheduling, FIFO promotion and provenance.
- [Run lifecycle](execution/runs.md) — durable Run state, ownership, stop and completion boundaries.
- [Agent loop](flow/agent-execution-loop.md) — model/tool iteration and foreground work.
- [Event transcript](execution/transcript.md) — event types, model-visible history and turn markers.
- [Durable actions](execution/actions.md) — operation admission, progress, results and continuation.
- [Subagents](execution/subagents.md) — hierarchy, inheritance, capacity, tools and direct-parent delivery.
- [Toolkit State](execution/tool-state.md) — namespaces, execution binding and private-state operation boundaries.
- [Run recovery](flow/run-resume.md) — takeover, retries and interrupted work.
- [Context compaction](flow/context-compaction.md) — model input budgets and durable continuity summaries.
- [Memory](domain/memory.md) — Saved knowledge, Historical synthesis, visibility and human management.
- [Session lifecycle](execution/session-lifecycle.md) — pinning, archive, retention, restore and irreversible purge.
- [Agent deletion](domain/agent-deletion.md) — decommission admission, cleanup dependencies and terminal gates.

## Ongoing and scheduled objectives

- [Goals and Todos](automation/goals.md) — explicit objectives, independent task lists and idle continuation.
- [Routines](domain/routine.md) — usefulness judgment, independent occurrences, events and notifications.
- [Scheduled Tasks](domain/scheduled-task.md) — one-time/cron definitions, explicit quiet-completion permission, occurrence tools and inspectable terminal results.
- [Periodic infrastructure](flow/periodic-execution.md) — maintenance jobs and bounded work admission.

## Models and provider execution

- [Model catalog](domain/model-catalog.md) — account-scoped discovery, capabilities and pricing projections.
- [Model selection](models/selection.md) — candidate chains, Workspace defaults, health and frozen operation profiles.
- [Request capabilities](models/request-capabilities.md) — built-in opt-ins and actual request admission.
- [ChatGPT OAuth](flow/chatgpt-oauth.md) — subscription authorization, refresh and entitlement.
- [Kimi OAuth](flow/kimi-oauth.md) — experimental subscription connection.
- [xAI OAuth](flow/xai-oauth.md) — experimental subscription identity, separate from API keys.
- [xAI API keys](flow/xai-api-key.md) — stable developer-key discovery and execution.
- [OpenRouter API keys](flow/openrouter-api-key.md) — account models, credit usage and publisher identity.
- [Inference authority](domain/inference-authority.md) — Agent bearer lifecycle and current candidate authorization.
- [Inference Proxy](domain/inference-proxy.md) — independent proxy and provider-wire boundary.

## Connections, tools and instructions

- [Toolkits](domain/toolkit.md) — connection ownership, CRUD, mounting and availability.
- [Personal connections](tools/personal-connections.md) — personal management, allowance and User-root execution.
- [GitHub](tools/github.md) — connection wizard, account authority and multi-installation routing.
- [Google](domain/google-connection.md) — typed Gmail, Calendar and Drive access with actual OAuth grants.
- [MCP OAuth](flow/mcp-oauth.md) — shared connection setup and runtime refresh.
- [Tool discovery](tools/discovery.md) — names, snapshots, search and model-visible working sets.
- [Instructions and Skills](tools/instructions.md) — managed Skills, filesystem instructions and Claude rules.
- [Runtime tool execution](tools/runtime-execution.md) — credentials, network authority and Runtime Hooks.

## Managed compute and resources

- [Runtime Providers](domain/runtime-provider.md) — registration, authentication and infrastructure ownership.
- [Runtime capability and profiles](runtime/profiles.md) — compute opt-in, exact selection and Workspace policy.
- [Runtime control](flow/agent-runtime-control.md) — authenticated Runner commands, transport and web exposure.
- [Runtime persistence](flow/agent-runtime-persistence.md) — Workspace durability, environment and configuration state.
- [Projects and worktrees](runtime/projects.md) — working folders, automatic policy, eligibility and cleanup ownership.
- [File exchange](flow/file-exchange-storage.md) — attachments, Artifacts, VFS and output materialization.
- [Interactive terminals](runtime/terminal.md) — Session identity and authenticated terminal control.
- [Session Browser](flow/session-browser.md) — Runner-owned pages, human help and live attachment.

## External conversations

- [External Channels](domain/external-channel.md) — connection ownership, routing, bindings, Primary and event projection.
- [Ingress](flow/external-channel-provider-ingress.md) — provider authentication, normalization and durable admission.
- [Authorization](flow/external-channel-authorization.md) — principals, approvals, grants and context release.
- [Delivery](flow/external-channel-delivery.md) — publication tools, Channel Work, files and provider presentation.
- [Lifecycle](flow/external-channel-lifecycle.md) — disconnect, archive, restore, purge and decommission effects.

## Product surfaces and delivery engineering

- [Chat presentation](surfaces/chat.md) — draft/concrete layout, composer, viewport and Markdown rendering.
- [Session titles](surfaces/session-titles.md) — manual names and conditional auxiliary title generation.
- [Chat resynchronization](flow/chat-session-resync.md) — subscriptions, REST baselines and timeline recovery.
- [Context Inspector](flow/session-context-inspector.md) — prompt, context, usage and raw-event disclosure.
- [Web theme](domain/web-theme.md) — semantic surfaces and contrast.
- [Testing and CI](flow/test-strategy-e2e-primary.md) — minimal core E2E and lower-layer contracts.
- [iOS builds](flow/ios-build.md) — native bootstrap, simulator verification and unsigned artifacts.
- [Public releases](flow/public-release.md) — protected publication and downstream handoff.

## Evidence and maintenance

Requirements explain confirmed intent, ADRs explain decisions, Designs explain
implementation-time mechanisms, and code/tests supply implementation evidence.
These are references outside the wiki, not migrated source pages. Resolve conflicts
explicitly instead of blending past and present behavior. A selected reference is
an entrypoint, not a guarantee of coverage or a blanket verification stamp.

Each detailed contract has one owning page. Related pages explain the connection
and link to that owner. Integrate verified changes into those pages and lint the
affected subgraph under [the maintenance guide](AGENTS.md). Git/PR history records
changes; this index is editorial navigation, not a machine-generated coverage map.
