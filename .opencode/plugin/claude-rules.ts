/**
 * claude-rules: Claude Code's .claude/rules/ spec implemented as an OpenCode plugin.
 *
 * Loads rule markdown files from:
 *   - `<projectRoot>/.claude/rules/**` and `<projectRoot>/.opencode/rules/**`
 *   - `~/.claude/rules/**` and `~/.opencode/rules/**` (user-level)
 *   - any `.claude/rules/` or `.opencode/rules/` found by walking UP from
 *     an accessed file to the project root (nested rules)
 *
 * `projectRoot` is `ctx.worktree` when OpenCode sets it (e.g. via the
 * X-OpenCode-Directory header), otherwise `ctx.directory`, otherwise cwd.
 *
 * - Rules without `paths` frontmatter in top-level roots (project root /
 *   user home) are injected every transform (unconditional).
 * - Rules with `paths` globs are injected when the agent accesses a
 *   matching file via Read/Edit/Write. Pairs persist for the session.
 * - Nested rules without `paths` are implicitly scoped to their subtree:
 *   activate when any file in that subtree is accessed.
 * - Files accessed outside the project subtree get only the unconditional
 *   top-level rules; nested lookup is skipped.
 *
 * Symlinks are resolved by realpath so symlink loops terminate safely.
 * External symlinks (Claude spec: share rules across projects) are
 * followed.
 *
 * Runtime: Node.js APIs only.
 *
 * This file is the plugin entry. OpenCode's loader scans every `.ts` file
 * under `.opencode/plugin/` and, for each, iterates its named exports
 * expecting every one to be either a function or `{ server: Plugin }`. Any
 * non-function export (e.g. a `const TTL_MS = 60_000`) makes the whole
 * module fail with "Plugin export is not a function". So this file exports
 * ONLY the factory, and all pure helpers / constants live in
 * `../lib/core.ts` (outside `plugin/`, so the loader never touches it).
 *
 * Why we avoid tool.execute.after:
 *   `tool.execute.after.output.output` mutations are silently dropped
 *   (https://github.com/anomalyco/opencode/issues/13574), so path-scoped
 *   injection goes through `experimental.chat.system.transform` rather than
 *   attaching to the Read tool result. We capture accessed paths in
 *   `tool.execute.before` and drain them on the next system transform.
 */

import * as fs from "node:fs";
import * as path from "node:path";

import {
  DEBUG,
  TRACKED_TOOLS,
  allKnownRules,
  buildInjectionText,
  dbg,
  ensureNestedRulesForFile,
  ensureSession,
  info,
  isUnderDir,
  loadCachedTopLevelRules,
  logOnce,
  resolveHome,
  resolveProjectRoot,
  type PluginContext,
} from "../lib/core";

export const ClaudeRulesPlugin = async (ctx: PluginContext) => {
  const projectRoot = resolveProjectRoot(ctx);
  const home = resolveHome();
  info(`loaded for ${projectRoot} (home=${home ?? "unknown"})`);
  if (DEBUG) dbg("ctx", { worktree: ctx.worktree, directory: ctx.directory });

  return {
    "experimental.chat.system.transform": async (
      input: { sessionID?: string },
      output: { system: string[] },
    ) => {
      try {
        await loadCachedTopLevelRules(projectRoot, home);
        const rules = allKnownRules(projectRoot, home);
        const sessionID = input.sessionID ?? "__global__";
        const state = ensureSession(sessionID);
        const pending = state.pendingAccessedPaths.length;
        const { text, unconditionalCount, scopedCount } = buildInjectionText(
          state,
          rules,
        );
        if (text) {
          // Append to the existing main system-prompt block (system[0])
          // rather than pushing a new role:"system" message. Keeping rule
          // content inside the same block as the agent prompt / AGENTS.md
          // guarantees it reaches the model at the same priority and is
          // not dropped by any downstream consolidation in the AI SDK or
          // the provider's prompt caching layer.
          if (output.system.length > 0) {
            output.system[0] = `${output.system[0]}\n\n${text}`;
          } else {
            output.system.push(text);
          }
        }
        dbg(
          `transform session=${sessionID} rules=${rules.length} pending=${pending} unconditional=${unconditionalCount} scoped=${scopedCount} bytes=${text.length}`,
        );
      } catch (e) {
        logOnce("transform", e);
      }
      return output;
    },

    "tool.execute.before": async (
      input: { tool: string; sessionID: string; callID: string },
      output: { args: Record<string, unknown> },
    ) => {
      try {
        const toolId = (input.tool || "").toLowerCase();
        if (!TRACKED_TOOLS.has(toolId)) return;
        const args = output.args ?? {};
        const fp =
          (args.filePath as string | undefined) ??
          (args.file_path as string | undefined) ??
          (args.path as string | undefined);
        if (typeof fp !== "string" || fp.length === 0) {
          dbg(`before: ${toolId} has no file path in args`, args);
          return;
        }
        const abs = path.isAbsolute(fp) ? fp : path.resolve(projectRoot, fp);
        let real: string;
        try {
          real = fs.realpathSync(abs);
        } catch {
          real = abs;
        }
        if (!isUnderDir(real, projectRoot)) {
          dbg(
            `before: ${real} outside projectRoot ${projectRoot}, skipping walk-up`,
          );
        } else {
          await ensureNestedRulesForFile(real, projectRoot, home);
        }
        const state = ensureSession(input.sessionID ?? "__global__");
        state.pendingAccessedPaths.push(real);
        dbg(`queued ${toolId} ${real}`);
      } catch (e) {
        logOnce("before", e);
      }
      return output;
    },
  };
};
