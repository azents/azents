# claude-rules OpenCode plugin

Implements Claude Code's [`.claude/rules/`](https://code.claude.com/docs/en/memory#organize-rules-with-claude/rules/) spec as an OpenCode plugin. Each worktree can ship modular rule files that are injected into the model's system prompt either unconditionally or scoped to file-path globs.

## What it does

The plugin discovers rules from three classes of locations:

1. **Project root** (`ctx.worktree` in OpenCode, the worktree path in Codingbot):
   - `<projectRoot>/.claude/rules/**/*.md`
   - `<projectRoot>/.opencode/rules/**/*.md`
2. **User home** (spec-compliant user-level rules; globs resolve against the current project):
   - `~/.claude/rules/**/*.md`
   - `~/.opencode/rules/**/*.md`
3. **Nested rule-roots** discovered lazily by walking UP from each accessed file to the project root. If `<projectRoot>/packages/web/.claude/rules/foo.md` exists, it is loaded the first time the agent reads any file under `packages/web/`. Globs in nested rules resolve against the nested directory (so `paths: ["src/**/*.ts"]` in `packages/web/.claude/rules/` matches files under `packages/web/src/`).

Each rule is a markdown file, optionally with YAML frontmatter:

```markdown
---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Python rule body

Rules are injected as <system-reminder> blocks into the model's system prompt.
```

Semantics:

- **Top-level (project root / user home) without `paths`**: unconditional. Pushed on every LLM turn.
- **Top-level with `paths`**: activated when the agent Read/Edit/Writes a matching file. Once active, pushed on every subsequent turn in the session.
- **Nested without `paths`**: implicitly scoped to the nested subtree. Activated when any file under the nested dir is accessed.
- **Nested with `paths`**: activated when a file matching the glob (relative to the nested dir) is accessed.
- **Files outside the project root**: top-level unconditional rules still inject; nested lookup is skipped.

Priority order in the system prompt: user-level → project-root → nested.

Symbolic links are resolved and deduped by realpath. Symlink loops terminate safely. The same rule file discoverable via multiple paths (symlinked shared rules) appears in the injection pipeline exactly once. External symlinks (e.g. `ln -s ~/shared-rules .claude/rules/shared`) are followed per the [Claude spec](https://code.claude.com/docs/en/memory#share-rules-across-projects-with-symlinks); this means the rule author can pull in any readable file, so only authors with commit access to the project should add rules. In Codingbot the worktree reflects trusted branch contents, and the `allowed_users` filter in the bot config gates who can trigger a session.

## Files

```
.opencode/
├── package.json                     # deps: gray-matter, picomatch
├── opencode.jsonc                   # no plugin registration needed (auto-discovery)
└── plugin/
    ├── claude-rules.ts              # plugin entry, auto-discovered by OpenCode
    ├── README.md                    # this file
    └── __tests__/
        ├── claude-rules.test.ts     # bun test suite
        └── fixtures/                # fixture worktrees for tests
```

## Development

Deps install (once):

```bash
cd python/codingbot/.opencode && bun install
```

Run tests:

```bash
cd python/codingbot/.opencode && bun test
```

`bun test` expects Bun 1.1+. The production image uses the pinned `oven/bun:1.1` for the `plugin-deps` build stage; the resulting `node_modules` is copied into `/home/codingbot/.config/opencode/node_modules` so plugin load costs nothing at session start.

## How injection works under the hood

- `experimental.chat.system.transform(input, output)` hook pushes rule blocks onto `output.system`. Per-session `Set`s prevent re-injection.
- `tool.execute.before(input, output)` captures `output.args.filePath` (also falls back to `file_path`/`path`) for `read`/`edit`/`write` tool calls. Paths are resolved to realpath and queued on the session.
- The next `experimental.chat.system.transform` drains the queue and injects matching scoped rules.

We don't use `tool.execute.after` because `output.output` mutations are silently dropped ([issue #13574](https://github.com/anomalyco/opencode/issues/13574)).

## Integration test recipe

1. `docker compose build codingbot`.
2. Confirm plugin loads on start by grepping the OpenCode server log for `[claude-rules] loaded for`.
3. Prepare a sample worktree under the mounted `/worktrees/` volume with:
   - `.claude/rules/always.md`: no frontmatter, body `ALWAYS_RULE_TOKEN`.
   - `.claude/rules/scoped.md`: frontmatter `paths: ["src/**/*.py"]`, body `SCOPED_RULE_TOKEN`.
4. Trigger an Codingbot session against that worktree (mention the bot on a sample issue).
5. Inspect the session's messages via the OpenCode REST API (`GET /session/{id}/messages` with `X-OpenCode-Directory`). Assert:
   - Turn 1 system prompt contains `ALWAYS_RULE_TOKEN` (count 1).
   - No `SCOPED_RULE_TOKEN` yet.
6. Prompt the agent to read `src/foo.py`. On the next turn, assert `SCOPED_RULE_TOKEN` is present (count 1).
7. Prompt another read of `docs/README.md`. Assert the scoped token count is still 1 (no duplicate).
8. Across all turns, `ALWAYS_RULE_TOKEN` count stays at 1.

## Smoke tests

**Symlink loop**: create a loop on the host and confirm the session does not hang:

```bash
mkdir -p /tmp/wt/.claude/rules
ln -sf loop-b.md /tmp/wt/.claude/rules/loop-a.md
ln -sf loop-a.md /tmp/wt/.claude/rules/loop-b.md
echo "# real" > /tmp/wt/.claude/rules/real.md
```

`real.md` must still be picked up; the loop files must not cause hang or OOM.

**`OPENCODE_DISABLE_DEFAULT_PLUGINS=1` compatibility**: the Dockerfile sets this flag to disable OpenCode's built-in plugins. User plugins (including this one) should still load. Verify by searching the boot log for `[claude-rules] loaded for`.

## Limitations and version pinning

- Relies on the `experimental.chat.system.transform` hook: the `experimental.` prefix means the name may change in a future OpenCode release. Image pins OpenCode at `1.14.19` (see `Dockerfile` `OPENCODE_VERSION`).
- When upgrading OpenCode, verify the hook name is still present. If renamed, register both old and new names in the plugin for backward compatibility.
- YAML frontmatter that is structurally invalid causes the affected rule to be skipped with a warning logged to stderr; neighboring rules load normally.
