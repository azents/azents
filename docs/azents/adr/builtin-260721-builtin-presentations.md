---
title: "Complete Specialized Presentation Coverage for Builtin Tools"
created: 2026-07-21
tags: [architecture, frontend, chat, tools, ux, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: builtin-260721
historical_reconstruction: true
migration_source: "docs/azents/adr/0177-complete-builtin-tool-presentations.md"
---

# builtin-260721/ADR: Complete Specialized Presentation Coverage for Builtin Tools

## Context

[known-260720/ADR](./known-260720-known-tools-through-validated-frontend-adapters.md) established validated, source-aware frontend adapters, one shared disclosure shell, closed presentation families, privacy-reviewed summary prominence, and permanent Generic fallback. The first implementation slice specialized ten stable Runtime tools, while nineteen source-less builtin tools still use Generic argument/output presentation.

The remaining tools span file delivery, persistent Memory, Goal and Todo state, filesystem Skills, subagent collaboration, and deferred Tool Search. Several already project a separate product surface such as attachments, Goal/Todo state, Skill activity, or the Subagent tree. Specialized tool presentation must explain the invocation and result without duplicating or taking ownership from those surfaces.

## Constraints

- Preserve the canonical identity and Generic fallback rules from [known-260720/ADR](./known-260720-known-tools-through-validated-frontend-adapters.md).
- Do not specialize Toolkit-owned calls from visible-name collisions.
- Keep attachment ownership and Activity boundaries unchanged.
- Keep Goal, Todo, Skill, and Subagent state surfaces authoritative for their domain state.
- Keep memory content, Goal/Todo text, Skill bodies, inter-agent messages, search queries, file URIs, and arbitrary result text out of collapsed summaries.
- Prefer existing result contracts and frontend projection data; do not require a backend or public API contract change merely to activate a presentation.
- Use the existing shared disclosure shell and closed presentation families rather than one bespoke outer component per tool.

## Scope

The intended coverage is all currently unspecialized source-less builtin tools:

- File: `read_image`, `import_file`;
- Memory: `save_memory`, `list_memories`, `get_memory`, `search_memories`, `delete_memory`;
- Goal: `get_goal`, `create_goal`, `update_goal`;
- Todo: `update_todo`;
- Skill: `load_skill`;
- Subagent: `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, `list_agents`;
- Tool Search: `tool_search`.

The nineteen source-less client builtins are the primary coverage scope. The existing provider-hosted `web_search` presentation is also refined in this work because its icon, collapsed query, and expanded result treatment share the same Activity visual contract. `image_generation` remains outside this scope because its existing provider presentation and attachment ownership already satisfy the requested behavior.

## Accepted Decisions

### Use domain-recognizable icons and existing domain action components

The remaining builtin presentations use icons that match their product domain rather than a generic tool icon:

- image operations use the image icon;
- `import_file` uses the download icon;
- Memory operations use the brain icon;
- Goal operations use the existing Goal icon;
- Todo operations use the checkbox icon;
- `load_skill` reuses the same component and visual language as the existing Skill action;
- Subagent operations use the existing Subagent icon; and
- `tool_search` uses the search icon.

Icon selection is family-owned and decorative when the localized action label is present. It does not change disclosure, status, accessibility, or Generic fallback ownership.

### Complete all remaining builtin presentations through domain families

All nineteen currently unspecialized source-less builtin tools receive exact validated frontend adapters. They reuse the shared disclosure shell and are rendered through eight domain presentation families:

1. Image;
2. Import file;
3. Memory;
4. Goal;
5. Todo;
6. the existing Skill action presentation;
7. Subagent collaboration; and
8. Tool Search.

Each exact tool identity retains its own action, argument schema, terminal result decoder, lifecycle behavior, and Generic fallback. Domain families share only the visual and interaction contract; they do not erase operation-specific semantics.

### Keep domain state surfaces authoritative and tool details historical

Existing Goal, Todo, Skill, Subagent Tree, and attachment surfaces remain authoritative for current product state and primary file delivery. Specialized tool presentation explains the invocation and its result at that point in transcript history.

- `read_image` does not duplicate an image preview inside its tool disclosure; the attachment surface owns preview and download.
- Goal and Todo tool details may show the historical objective or item snapshot, while the Goal/Todo controls continue to own current state.
- `load_skill` uses the same visual component and expanded Skill body presentation as the existing Skill action.
- Subagent tool details show the historical operation result, while the Subagent Tree owns current agent state.

### Permit bounded resource identities but hide free-form payloads in collapsed rows

Collapsed summaries may show validated, bounded resource identities when they materially distinguish the operation:

- file basenames and explicit destination labels;
- Memory entry names and scope;
- Skill names or slugs;
- Subagent names or paths; and
- structured result counts and statuses.

Collapsed summaries do not show Memory content, Goal objectives, Todo item content, Skill bodies, inter-agent messages, subagent tasks, Tool Search queries, search patterns, file URIs, or arbitrary output. Those values appear only in approved expanded semantic detail or Raw data.

### Activate every remaining tool without requiring backend contract changes

The first complete coverage implementation is frontend-only. Adapters use exact validated arguments, stable JSON results where available, opaque text where semantic parsing is not justified, existing attachments, and existing state events.

A tool remains specialized even when only its requested operation can be stated safely. It must not infer missing terminal facts from arbitrary prose. For example, `import_file` can show an explicit input destination, but when the destination was server-generated and exists only in an unstructured result string, the semantic presentation omits that fact and preserves the result through Raw data.

Malformed JSON, incompatible result shapes, unsupported phases, missing required structured output, or parser drift fall back locally to Generic. New backend metadata may improve a future presentation but is not a prerequisite for complete coverage.

### Remove filler labels from Generic collapsed rows

Generic fallback remains the permanent raw compatibility surface, but its collapsed row shows only the canonical tool name and lifecycle status. It does not add filler copy such as `Generic details` or `General details` merely to occupy the subject position.

Expanding the row continues to show the retained arguments and result with their ordinary field labels. Removing collapsed filler copy does not weaken raw inspection, lifecycle status, accessibility, or call-local fallback.

### Keep the raw-data action visible on every Tool row

Every client Tool row reserves and renders the right-side `…` action regardless of whether the call is specialized or Generic and regardless of whether arguments or result content are currently non-empty. This keeps the row grid stable and makes diagnostic access predictable.

The action opens the call's raw diagnostic surface using the canonical retained arguments and result available for that lifecycle phase. Live updates refresh the same diagnostic surface. The fixed action slot must not change the left-side chevron, icon, label, or status alignment.

### Use operation-specific summaries and bounded expanded detail

The accepted tool behavior is:

| Tool              | Collapsed action                          | Expanded semantic detail                                                             |
| ----------------- | ----------------------------------------- | ------------------------------------------------------------------------------------ |
| `read_image`      | image read plus basename                  | no duplicate preview; attachment owns the image                                      |
| `import_file`     | file import plus known destination label  | explicit destination, source kind, overwrite and temporary-file facts when validated |
| `save_memory`     | save Memory plus name and scope           | name, scope, type, and description; content remains Raw-only                         |
| `list_memories`   | list Memories plus filters                | returned list as one opaque readable result                                          |
| `get_memory`      | load Memory plus name and scope           | returned Memory body and metadata as one readable result                             |
| `search_memories` | search Memories plus scope                | query and opaque ranked result in expanded detail                                    |
| `delete_memory`   | delete Memory plus name and scope         | row-only success when terminal result validates                                      |
| `get_goal`        | inspect Goal plus validated status        | historical objective, status, and timestamps                                         |
| `create_goal`     | create Goal                               | historical objective, active status, and creation time                               |
| `update_goal`     | complete or block Goal according to input | historical objective, resulting status, and update time                              |
| `update_todo`     | update Todo plus count, or clear Todo     | historical item list and statuses for replacement operations                         |
| `load_skill`      | load Skill plus validated name or slug    | existing Skill action body presentation                                              |
| `spawn_agent`     | spawn Subagent plus target name           | task, created path, fork selection, and non-default inference overrides              |
| `send_message`    | send message plus target agent            | message and queued/not-found outcome                                                 |
| `followup_task`   | assign follow-up plus target agent        | task and assigned/not-found outcome                                                  |
| `wait_agent`      | wait for Subagents                        | timeout request and validated mailbox/idle/timeout result                            |
| `interrupt_agent` | interrupt Subagent plus target            | validated previous status                                                            |
| `list_agents`     | list Subagents plus count                 | compact historical agent/status list with last task expanded-only                    |
| `tool_search`     | search tools plus activated count         | query, activated tool names, sources, descriptions, and reduced-limit notice         |

## Existing Decisions Retained

- Adapters validate exact first-party builtin identities and lifecycle-specific payloads.
- The shared disclosure shell owns status, accessibility, raw diagnostics, and fallback.
- Presentation views are selected from closed families and do not own arbitrary outer cards.
- Invalid, historical, malformed, unsupported-phase, and adapter-error calls fall back locally to Generic.
- Raw payloads remain diagnostic data and are never reconstructed from semantic presentation.

## Migration provenance

- Historical source filename: `0177-complete-builtin-tool-presentations.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
