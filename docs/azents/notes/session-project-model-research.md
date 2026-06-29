---
title: "Session Project Model Research and Discussion Summary"
created: 2026-06-29
tags: [architecture, product, backend, engine, frontend]
---

# Session Project Model Research and Discussion Summary

This note captures unresolved product and architecture discussion around Azents Project modeling, multi-project sessions, git-specific project flows, and comparable concepts in Codex / Claude Code.

This is **not an ADR** and not a final design. It is a research and discussion handoff document so a new session can recover the context without reading the full chat transcript.

## Why this note exists

Azents currently has a session-scoped Project registry, but the team is still evaluating whether the current model is the right long-term abstraction.

Current implementation is useful but raises questions around:

- how a new session should naturally bootstrap its Project set;
- how a main / team-primary session should relate to multiple Projects;
- how multi-repo and non-git Project workflows should work;
- whether Projects can change while a session is running;
- how git clone, worktrees, archive cleanup, and file-browser git views should fit;
- how repo-scoped `AGENTS.md` and future skills should be loaded in a multi-project session.

## Current Azents implementation snapshot

As of the branch inspected in this research (`research/project-concept`), Azents has a session-owned Project registry.

Relevant implementation areas:

- `python/apps/azents/src/azents/rdb/models/session_workspace_project.py`
- `python/apps/azents/src/azents/repos/session_workspace_project/__init__.py`
- `python/apps/azents/src/azents/repos/session_workspace_project/data.py`
- `python/apps/azents/src/azents/services/session_workspace_project/__init__.py`
- `python/apps/azents/src/azents/api/public/chat/v1/__init__.py`
- `python/apps/azents/src/azents/api/public/chat/v1/data.py`
- `python/apps/azents/src/azents/engine/tools/builtin.py`
- `python/apps/azents/src/azents/engine/tools/builtin_agents.py`
- `typescript/apps/azents-web/src/trpc/routers/chat.ts`
- `typescript/apps/azents-web/src/features/chat/workspace/components/ProjectPanel.tsx`
- `typescript/apps/azents-web/src/features/chat/workspace/containers/useWorkspacePanelContainer.ts`
- `typescript/apps/azents-web/src/features/agents/AgentProjectsPage.tsx`

Current conceptual behavior:

- A Project is a registered directory under the runtime workspace.
- Project path normalization currently targets `/workspace/agent`.
- `/workspace/agent` itself is not a Project.
- Current valid Project paths are direct children such as `/workspace/agent/azents`.
- Nested Project paths are rejected to avoid parent/child Project overlap.
- Projects are owned by `AgentSession`, not `AgentRuntime`.
- New team sessions currently snapshot-copy Project rows from the team-primary session.
- Runtime tooling loads session Projects and renders them into the config prompt.
- AGENTS.md appendix behavior is scoped around registered Project paths.

Current public API shape:

- list session Projects;
- register an existing runtime folder as a session Project;
- delete a session Project registration;
- list Project registration requests;
- approve/reject Project registration requests.

Current registration semantics:

- Registration validates session access and workspace membership.
- Registration requires an active session and a ready runtime.
- Registration checks that the target path exists as a real runtime directory.
- Deleting a Project deletes the registry row, not the physical directory.

Important current limitation:

- There is registration request storage and approve/reject API, but the actual agent-facing path for creating a registration request still needs verification / design.

## Related Azents decisions already recorded

### ADR-0074: Primary Agent Sessions and Team-First Multi-Session UX

Relevant points from `docs/azents/adr/0074-primary-agent-sessions.md`:

- `AgentRuntime` and `AgentSession` are sibling models under `Agent`.
- `AgentRuntime` owns the physical runtime workspace and runner lifecycle.
- `AgentSession` owns transcript, input buffers, run state, and session Project registrations.
- Project registrations belong to `AgentSession`, not `AgentRuntime`.
- Multiple sessions may register Projects pointing to the same physical path.
- A session may have multiple Projects when a task spans repositories.
- New team sessions currently copy Projects from the team-primary session.
- Git worktree automation is deferred.

This note questions whether the snapshot-copy rule is a good long-term bootstrap model, without changing the ADR by itself.

## External research: Codex

Codex has related but not identical concepts.

### Codex `AGENTS.md`

Codex uses `AGENTS.md` as project/repository-scoped instructions.

Observed from Codex source (`codex-rs/core/src/agents_md.rs`) and official documentation:

- Codex determines a project root by walking upward from the current working directory.
- Default project root marker is `.git`.
- If no marker is found, only the current working directory is considered.
- Codex collects `AGENTS.md` files from project root down to current working directory.
- Codex does not walk past the project root.
- `AGENTS.override.md` is a preferred local override candidate before `AGENTS.md`.
- Additional fallback filenames are configurable.
- Loaded instructions retain provenance and can be labeled by environment when multiple project environments contribute instructions.

Primary reference:

- https://developers.openai.com/codex/guides/agents-md
- https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs

### Codex project-local config and trust

Codex also has project-local `.codex/config.toml` loading.

Observed from Codex source (`codex-rs/config/src/loader/mod.rs`, `codex-rs/config/src/config_toml.rs`):

- Codex walks project root to current working directory and loads `.codex/config.toml` layers.
- Project-local config, hooks, and exec policies are gated by a project trust decision.
- Trust is configured via user-level `[projects."<path>"] trust_level = "trusted"` / `"untrusted"` style config.
- Project-local config is sanitized; some keys are ignored in project-local config and must live in user-level config.
- Worktree-related edge cases exist: for linked worktrees, Codex preserves ordinary worktree-local config while replacing hook declarations with matching root-checkout hooks.

Primary reference:

- https://github.com/openai/codex/blob/main/codex-rs/config/src/loader/mod.rs
- https://github.com/openai/codex/blob/main/codex-rs/config/src/config_toml.rs

### Codex workspace roots and sandbox roots

Codex has `workspace_roots` / symbolic `:workspace_roots` permission concepts.

Observed from Codex source (`codex-rs/core/src/config/mod.rs`, `codex-rs/core/src/config/permissions.rs`):

- Runtime/thread workspace roots are materialized into filesystem permission profiles.
- This is permission/sandbox-oriented, not the same as Azents Project registry.

### Codex worktrees

Codex app/cloud also uses worktree concepts for isolated coding work.

Reference:

- https://developers.openai.com/codex/app/worktrees

### Codex comparison summary

Codex is mostly implicit and `cwd`/git-root driven:

```text
cwd
 -> find project root using .git / project markers
 -> load AGENTS.md from root to cwd
 -> load .codex/config.toml if project is trusted
 -> apply sandbox/workspace roots
```

Azents is currently explicit and session-registry driven:

```text
AgentSession
 -> registered Project rows
 -> /workspace/agent/<project> paths
 -> prompt includes registered Projects
 -> AGENTS.md appendix is scoped to registered Projects
```

Key difference:

- Codex is local/coding-agent oriented and can rely heavily on `cwd`.
- Azents is server/session/multi-user oriented, so relying only on `cwd` would be risky.

Codex ideas worth borrowing carefully:

- hierarchical `AGENTS.md` discovery and provenance;
- local override concept like `AGENTS.override.md`;
- project-local config gated by trust;
- worktree-aware config/hook behavior;
- explicit instruction source provenance.

Codex ideas to avoid copying directly:

- treating `cwd` as the only Project selector;
- assuming git root equals user-facing Project;
- auto-applying project-local config without a trust model;
- making worktree creation part of generic Project registration.

## External research: Claude Code

Claude Code has similar but simpler concepts:

- `CLAUDE.md` memory / instruction files;
- working-directory-centered context;
- `--add-dir` style additional directory access;
- project/user/local memory distinctions.

References:

- https://docs.anthropic.com/en/docs/claude-code/memory
- https://docs.anthropic.com/en/docs/claude-code/cli-reference

Claude Code is useful as a comparison point, but it does not appear to model session-owned multi-Project registry the way Azents is attempting to.

## Discussion point 1: Session-specific Projects and bootstrap

### Current concern

Azents can structurally assign Projects per session, but current bootstrap is not intuitive:

```text
team-primary session Projects
 -> copied into newly created session
```

Concerns:

- Users do not naturally think “copy Projects from main session.”
- Adding paths as the way to define Projects feels low-level.
- If the main session holds the complete Project list and new sessions choose subsets, that may be better than copy-by-default, but still feels imperfect when session-bound worktrees are considered.
- The team-primary session risks becoming both:
  - the default long-running conversation; and
  - the source of truth for the Agent’s Project catalog.

### Requirement interpretation

The requirement is likely not “remove session Projects.”

More precise interpretation:

- There should be a distinction between Projects an Agent/Workspace knows about and Projects active in a particular session.
- A session should own the active binding / usage of Projects, not necessarily the canonical Project list itself.
- Bootstrap should be understandable as choosing Projects for a session, not copying from another conversation.

Possible vocabulary that may help future design:

- **Project Catalog**: logical Project candidates known to an Agent or Workspace.
- **Session Project Binding**: Project activation in a specific session.
- **Materialization**: how that Project appears in the runtime for that session, e.g. shared path, session worktree, clone, uploaded copy.

This vocabulary is only a research suggestion, not a settled decision.

## Discussion point 2: Multi-project intent and limits

### Intent

Azents intentionally wants to support multi-project sessions more strongly than Codex / Claude Code.

Motivations discussed:

1. **Multi-repo development**
   - Real work often spans backend, frontend, infra, docs, SDKs, and example repos.
   - Roadmap includes loading `AGENTS.md` and possibly skills from multiple repos.

2. **Main session should know many Projects**
   - The team-primary session is expected to support long-running work, similar to an agent that can be assigned broad ongoing responsibilities.
   - In that model, it is natural for the main session to be aware of multiple Projects.

### Important distinction

There is a difference between:

```text
main session can know about many Projects
```

and:

```text
every turn loads every Project's AGENTS.md / skills / context
```

The first is likely reasonable. The second can cause context pollution, instruction conflict, and skill ambiguity.

A possible future policy is:

```text
A session may know the full Project catalog, but active context should be selected by task, path, or explicit user/agent action.
```

### Multi-project issues

#### Skill name conflicts

In multi-repo sessions, duplicate skill names are expected, not exceptional.

Example:

```text
project-a: deploy
project-b: deploy
```

Potential design requirements:

- Skills likely need stable namespaced identities, e.g. `project_slug/skill_name` or internal `project_id/skill_name`.
- Short names may be allowed only when unambiguous.
- When ambiguous, the agent/UI should require project-qualified selection.

#### AGENTS.md conflicts

Multiple Projects may provide conflicting instructions.

Potential design requirements:

- AGENTS.md content should be labeled with Project identity and path provenance.
- Project-scoped instructions should apply only when working inside or explicitly discussing that Project.
- Prompt text should avoid blending all Project instructions as one undifferentiated instruction block.

#### Git and non-git Projects

Azents Projects may be git repos, ordinary folders, uploaded artifacts, generated directories, or external mounts.

Worktree support only applies to git Projects. Therefore worktree is not a property of Project in general; it is better understood as one possible materialization mode for a session binding.

## Discussion point 3: Modifying Projects during an active session

### Current concern

During development, a session may clone or create a new repo/folder and then want to add it to the Project list.

Examples:

- clone a related GitHub repo;
- download an SDK/example repo;
- generate a new folder;
- discover that another repo is required for the task.

### Requirement interpretation

If Azents supports multi-project work, session Project mutation during an active session is likely necessary.

Possible flows:

1. **User-initiated**
   - User opens Projects UI and adds a path/repo.

2. **Agent-initiated**
   - Agent discovers a needed repo/folder and asks for approval to add it.
   - Registration request model may be a natural fit for this.

3. **Operation-coupled**
   - Agent clones a repo, then registers it as a Project after approval.

### Design questions

- Does adding/removing a Project apply immediately or from the next turn?
- How is the model told that previous AGENTS.md instructions no longer apply?
- Should Project changes be represented as conversation events?
- How are skill conflicts handled when a new Project is added mid-session?
- Can an agent auto-register a folder it created, or must the user approve?

## Git-specific feature discussion

Git-specific functionality is desirable but should likely be modeled separately from generic Project registration.

### Git clone as Project bootstrap

Desired flow:

```text
select GitHub repo or provide URL
 -> clone into runtime workspace
 -> register as Project
 -> optionally add to current session and/or defaults
```

Why it feels natural:

- GitHub toolkit can discover repositories, permissions, default branches, PRs, issues, and clone URLs.
- Runtime can perform filesystem/git operations.
- Project registry can bind the resulting folder to a session.

Potential UX entry points:

1. Agent/Workspace Project management UI:
   - Add Project
   - Select from GitHub
   - Clone from URL
   - Register existing folder

2. New session creation:
   - Choose Projects for this session
   - Optionally clone/add a GitHub repository as part of creation

3. Agent-initiated request:
   - Agent says a repository is needed
   - UI shows an approval card with repo, destination, and materialization mode

Important separation:

```text
git clone = filesystem acquisition
Project registration = session/context binding
```

They may appear as one UX flow, but should remain separate domain operations.

### Worktree support

If a Project is known to be a git Project, a session may choose isolated worktree materialization.

Possible modes:

- shared checkout;
- session worktree;
- detached clone;
- branch checkout;
- non-git shared folder.

A session-bound worktree should likely be tied to the session Project binding/materialization, not to the logical Project itself.

Example:

```text
Logical Project: azents
Canonical path: /workspace/agent/azents

Main session binding:
  path: /workspace/agent/azents
  materialization: shared_checkout

Task session binding:
  path: /workspace/agent/.worktrees/session-123/azents
  materialization: session_worktree
  branch: session-123-task
```

### Session archive and worktree cleanup

If worktrees are session-bound, archive should consider cleanup.

However, unconditional deletion is risky.

Cleanup should probably be blocked or require confirmation when:

- there are uncommitted changes;
- there are untracked files;
- a branch has not been pushed;
- a PR is open or linked;
- cleanup checks fail;
- cleanup policy says preserve.

Possible policy:

```text
Archive session
 -> identify session-owned materializations
 -> auto-clean only safe, clean worktrees
 -> preserve or request confirmation for dirty/risky worktrees
```

### File browser git diff view

A git-aware file browser is a natural feature for Project-based workflows.

Potential UI surface:

- Project list with branch and dirty status;
- changed file count per Project;
- staged/unstaged/untracked groups;
- file-level diff view;
- PR link / branch / ahead-behind metadata;
- Project-level git status summary.

In multi-project sessions, git state should be grouped per Project. A root `/workspace/agent` diff view would mix unrelated repos and become confusing.

## Feasibility assessment

### Already feasible with current foundation

- Session-scoped Project list.
- Register existing runtime folder.
- Delete Project registry row.
- Validate runtime directory existence.
- Load Project list into runtime/tool prompt.
- Project tab UI and registration request UI.

### Feasible with moderate model/API additions

- Agent/Workspace-level Project catalog.
- Session creation with selected Project subset.
- Agent-initiated Project registration requests.
- Git repo detection via `.git`.
- GitHub repo picker / clone request.
- Project-scoped AGENTS.md provenance rendering.
- Namespaced Project skills.
- Git status and diff APIs for Project paths.

### More complex / needs careful design

- Session-bound worktree lifecycle.
- Archive-time cleanup with dirty state safety.
- Mid-session Project mutation and prompt supersession.
- Multi-project skill conflict resolution.
- Project-local config/hooks/tools with trust gating.
- Git and non-git materialization under one coherent model.

## Requirement rationality assessment

| Requirement / concern | Assessment | Notes |
| --- | --- | --- |
| Session-specific Projects | Reasonable | Session should own active working context, but maybe not canonical Project catalog. |
| Main session knows many Projects | Reasonable | But knowing all Projects should not imply loading all instructions every turn. |
| Multi-repo development | Strongly reasonable | Common real-world agent use case. |
| Session Project mutation | Likely required | Especially after clone/generation/discovery during a task. |
| Git clone bootstrap | Reasonable | Natural with GitHub integration, but should be separate from Project registration. |
| Worktree support | Reasonable but later-stage | Requires materialization/lifecycle model. |
| Archive worktree cleanup | Reasonable | Needs safety checks. |
| File browser git diff | Reasonable | Project-grouped UI is important in multi-project sessions. |
| Main-session Project copy | Weak long-term | Simple bootstrap, but conceptually confusing. |
| Path-only Project identity | Weak long-term | Works short-term, but insufficient for git/source/materialization semantics. |

## Possible long-term conceptual model

This is not a final recommendation, but a useful decomposition for future design.

```text
Project Catalog
  Logical Project known to an Agent or Workspace.
  Examples: azents repo, home repo, docs folder, SDK examples.

Project Source
  Where the logical Project comes from.
  Examples: GitHub repo, git URL, existing runtime path, uploaded archive, generated folder.

Session Project Binding
  The fact that a given AgentSession is using a Project.

Materialization
  How the Project is physically available in the runtime for that session.
  Examples: shared path, session worktree, clone, detached copy, non-git folder.

Context Policy
  How AGENTS.md, skills, memories, and future project-local config are loaded.
```

This decomposition helps avoid overloading “Project” with too many meanings.

## Possible staged roadmap

The team explicitly wants to reach this gradually, not implement everything at once.

### Stage 0: Stabilize current behavior

Goal:

- Keep session-scoped Project registry usable.
- Make current behavior clear in specs/docs.

Potential tasks:

- Verify migrations, OpenAPI/public client, backend tests, frontend typecheck.
- Document that current Project registration is path-only and session-owned.
- Clarify that Project deletion removes registry only, not files.
- Ensure runtime prompt accurately lists registered Projects.

### Stage 1: Improve session Project bootstrap without worktrees

Goal:

- Make new session Project selection more intuitive.

Potential tasks:

- Introduce a Project catalog or default Project set concept.
- Stop treating team-primary session as the conceptual source of truth, even if compatibility keeps copy behavior temporarily.
- Add session creation options for Project subset.
- Keep materialization simple: shared existing paths only.

### Stage 2: Support session-time Project mutation

Goal:

- Let Projects be added during a running session.

Potential tasks:

- Add agent-facing Project registration request creation.
- Represent Project changes as session events / context updates.
- Define “applies next turn” or immediate refresh semantics.
- Add prompt update behavior when Projects are added/removed.

### Stage 3: Multi-project context and skill namespace

Goal:

- Make multi-project instruction/skill loading safe.

Potential tasks:

- Label AGENTS.md instructions by Project.
- Define Project-scoped instruction applicability rules.
- Introduce namespaced skill identity.
- Reject or disambiguate duplicate short skill names.
- Add provenance to UI/debug views.

### Stage 4: GitHub clone bootstrap

Goal:

- Make GitHub repository selection and clone a natural Project acquisition flow.

Potential tasks:

- Add GitHub repo picker / URL clone flow.
- Separate clone operation from Project registration in domain model.
- Allow clone result to create Project catalog entry and/or session binding.
- Handle path conflicts and existing checkouts.

### Stage 5: Git-aware Project state and file browser

Goal:

- Add git visibility for registered git Projects.

Potential tasks:

- Detect git Projects.
- Expose branch/status/diff metadata per Project.
- Add Project-grouped changed files and diff view in file browser.
- Link PR/branch metadata when GitHub integration is available.

### Stage 6: Session-bound worktrees

Goal:

- Support isolated git workspaces per session.

Potential tasks:

- Add materialization kind to session bindings.
- Create worktrees from canonical/shared checkout.
- Define branch naming and base branch policy.
- Support mixed sessions: some shared paths, some worktrees, some non-git folders.
- Add archive cleanup policy with dirty-state safety checks.

### Stage 7: Project-local config and trust, if needed

Goal:

- If Azents loads project-local tools/hooks/config, gate it safely.

Potential tasks:

- Add Project trust model.
- Track who trusted what and for which scope.
- Make trust revocable.
- Avoid auto-applying untrusted project-local executable behavior.
- Keep registration distinct from trust.

## Open questions

1. Should Project catalog be owned by Workspace, Agent, or both?
2. Should the team-primary session automatically include all default Projects, or should it also have a binding set like any other session?
3. Is Project identity path-based, source-based, GitHub-repo-based, or explicit DB id based?
4. Should new sessions choose Projects explicitly, inherit defaults, or start empty?
5. Should Project selection happen at session creation, first run, or both?
6. How should Project additions/removals be reflected in model-visible context?
7. Can an agent auto-add Projects it creates, or must user approval always be required?
8. Should non-git Projects support any kind of isolated copy materialization?
9. How should duplicate skill names be displayed and invoked?
10. Should `AGENTS.override.md` or similar local override be supported in Azents?
11. If project-local config is added, what is the trust scope: user, workspace, agent, session, or Project?
12. How should archive behave when a session-bound worktree has uncommitted changes?
13. Should file browser git diff use runtime shell git commands, a dedicated runtime git API, or both?

## Short summary for a new session

Azents currently has session-owned path-based Project registration. The model is useful but likely too low-level for long-term multi-project workflows. The main unresolved issue is separating several concepts that are currently compressed into “Project”:

- logical Project known to an Agent/Workspace;
- session-specific activation/binding;
- physical runtime path;
- git clone/worktree materialization;
- project-scoped instructions and skills;
- future project-local config/trust.

Codex and Claude Code both provide useful references, but they are mostly `cwd`/repo-root oriented. Azents likely needs a more explicit registry and binding model because it is a server-side, multi-session, long-running agent product.

The safest near-term direction is to stabilize the current session registry while designing toward a separate Project catalog, session bindings, materialization modes, and provenance-aware context loading.
