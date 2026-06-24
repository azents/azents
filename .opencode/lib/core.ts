/**
 * claude-rules core: pure helpers + module state.
 *
 * Kept separate from the plugin entry so the entry file can export ONLY the
 * plugin factory (OpenCode's loader iterates every export in files under
 * `.opencode/plugin/` and expects each to be callable; a stray `const
 * TTL_MS = 60_000` would make it refuse the plugin with "Plugin export is
 * not a function").
 *
 * Rule discovery model:
 *
 *   - Top-level rule-roots (project root and user home) are pre-loaded at
 *     plugin factory time. Rules there without `paths` frontmatter are
 *     "unconditional": re-pushed on every transform.
 *   - Nested rule-roots (any `.claude/rules/` or `.opencode/rules/` inside
 *     a subtree of the project root) are discovered lazily by walking UP
 *     from each accessed file to the project root on `tool.execute.before`.
 *     Rules in a nested dir without `paths` are implicitly scoped to the
 *     subtree (walked-up dir); rules with `paths` are scoped with the glob
 *     resolved relative to that dir. Nested rules are never unconditional.
 *   - Files accessed outside the project root subtree get NO nested rule
 *     lookup; only top-level unconditional rules still apply (via the
 *     always-inject path).
 *
 * output.system is rebuilt by OpenCode on every LLM turn, so unconditional
 * rules are pushed every transform and active scoped pairs are persisted in
 * SessionState.activeScoped and re-pushed on every transform.
 */

import matter from "gray-matter";
import picomatch from "picomatch";
import * as fs from "node:fs";
import * as fsp from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Rule = {
  absPath: string;
  realPath: string;
  relPath: string;
  body: string;
  paths?: string[];
  matcher?: (absPath: string) => boolean;
  /**
   * True only for top-level rules (project root or user home) that had no
   * `paths` frontmatter. These are injected on every transform regardless
   * of file access.
   */
  unconditional: boolean;
};

export type SessionState = {
  activeScoped: Set<string>;
  pendingAccessedPaths: string[];
};

export type PluginContext = {
  worktree?: string;
  directory?: string;
};

export const TTL_MS = 60_000;
export const MAX_SESSIONS = 2000;
export const TRACKED_TOOLS = new Set(["read", "edit", "write"]);
export const DEBUG = process.env.CLAUDE_RULES_DEBUG === "1";

// Defense-in-depth: hard cap on walk-up iterations. Normal project trees are
// well under this; the guard is here so a pathological input can never hang.
export const MAX_WALK_UP = 200;

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function newSessionState(): SessionState {
  return { activeScoped: new Set(), pendingAccessedPaths: [] };
}

/**
 * DFS walker that follows symlinks but dedupes by realpath so symlink loops
 * terminate safely. The `visited` Set is shared across calls so multiple
 * rule-roots can share one dedup scope.
 */
export function walkMarkdown(
  startDir: string,
  visited: Set<string> = new Set(),
): string[] {
  const results: string[] = [];
  const queue: string[] = [startDir];
  while (queue.length > 0) {
    const cur = queue.pop()!;
    let real: string;
    try {
      real = fs.realpathSync(cur);
    } catch {
      continue;
    }
    if (visited.has(real)) continue;
    visited.add(real);
    let st: fs.Stats;
    try {
      st = fs.statSync(cur);
    } catch {
      continue;
    }
    if (st.isDirectory()) {
      let entries: string[];
      try {
        entries = fs.readdirSync(cur);
      } catch {
        continue;
      }
      for (const name of entries) queue.push(path.join(cur, name));
    } else if (st.isFile() && cur.endsWith(".md")) {
      results.push(real);
    }
  }
  return results;
}

export function compileMatcher(
  globs: string[],
  rulesBase: string,
): (absPath: string) => boolean {
  const absoluteGlobs: string[] = [];
  const relativeGlobs: string[] = [];
  for (const g of globs) {
    if (path.isAbsolute(g)) absoluteGlobs.push(g);
    else relativeGlobs.push(g);
  }
  const absMatch = absoluteGlobs.length
    ? picomatch(absoluteGlobs, { dot: true })
    : null;
  const relMatch = relativeGlobs.length
    ? picomatch(relativeGlobs, { dot: true })
    : null;
  return (abs: string) => {
    if (absMatch && absMatch(abs)) return true;
    if (relMatch) {
      const rel = path.relative(rulesBase, abs).split(path.sep).join("/");
      if (rel && !rel.startsWith("..") && relMatch(rel)) return true;
    }
    return false;
  };
}

function extractPathsField(data: unknown): string[] | undefined {
  if (!data || typeof data !== "object" || Array.isArray(data))
    return undefined;
  const raw = (data as Record<string, unknown>).paths;
  if (Array.isArray(raw)) {
    const arr = raw.filter((p): p is string => typeof p === "string");
    return arr.length > 0 ? arr : undefined;
  }
  if (typeof raw === "string" && raw.length > 0) return [raw];
  return undefined;
}

function withTrailingSep(dir: string): string {
  return dir.endsWith(path.sep) ? dir : dir + path.sep;
}

export function isUnderDir(absPath: string, dir: string): boolean {
  return absPath === dir || absPath.startsWith(withTrailingSep(dir));
}

function buildRelPath(
  absPath: string,
  projectRoot: string,
  home: string | null,
): string {
  if (isUnderDir(absPath, projectRoot)) {
    return path.relative(projectRoot, absPath).split(path.sep).join("/");
  }
  if (home && isUnderDir(absPath, home)) {
    return "~/" + path.relative(home, absPath).split(path.sep).join("/");
  }
  return absPath;
}

function buildRule(
  real: string,
  parsed: matter.GrayMatterFile<string>,
  opts: {
    globBase: string;
    subtreeBase: string | null;
    relPath: string;
  },
): Rule {
  const paths = extractPathsField(parsed.data);
  const unconditional = !paths && opts.subtreeBase === null;
  const rule: Rule = {
    absPath: real,
    realPath: real,
    relPath: opts.relPath,
    body: parsed.content.trim(),
    paths,
    unconditional,
  };
  if (paths) {
    rule.matcher = compileMatcher(paths, opts.globBase);
  } else if (opts.subtreeBase !== null) {
    // Nested rule without paths: implicitly matches any file in the subtree.
    const subtree = opts.subtreeBase;
    rule.matcher = (abs: string) => isUnderDir(abs, subtree);
  }
  return rule;
}

async function loadRulesFromRoot(opts: {
  baseDir: string;
  globBase: string;
  subtreeBase: string | null;
  projectRoot: string;
  home: string | null;
  visited: Set<string>;
}): Promise<Rule[]> {
  const rules: Rule[] = [];
  for (const dirName of [".claude", ".opencode"]) {
    const rulesDir = path.join(opts.baseDir, dirName, "rules");
    if (!fs.existsSync(rulesDir)) continue;
    for (const real of walkMarkdown(rulesDir, opts.visited)) {
      try {
        const raw = await fsp.readFile(real, "utf8");
        const parsed = matter(raw);
        rules.push(
          buildRule(real, parsed, {
            globBase: opts.globBase,
            subtreeBase: opts.subtreeBase,
            relPath: buildRelPath(real, opts.projectRoot, opts.home),
          }),
        );
      } catch (e) {
        console.error(`[claude-rules] Failed to load rule ${real}:`, e);
      }
    }
  }
  return rules;
}

/**
 * Load always-on rules: the project root's `.claude/rules` /
 * `.opencode/rules` and the user home's equivalents. User-level rules come
 * first so project rules win priority (appended later in the system array).
 */
export async function loadTopLevelRules(
  projectRoot: string,
  home: string | null,
): Promise<Rule[]> {
  const visited = new Set<string>();
  const rules: Rule[] = [];
  if (home && home !== projectRoot) {
    rules.push(
      ...(await loadRulesFromRoot({
        baseDir: home,
        // User-level rules apply to the current project: resolve their globs
        // against the project root, not against the user home.
        globBase: projectRoot,
        subtreeBase: null,
        projectRoot,
        home,
        visited,
      })),
    );
  }
  rules.push(
    ...(await loadRulesFromRoot({
      baseDir: projectRoot,
      globBase: projectRoot,
      subtreeBase: null,
      projectRoot,
      home,
      visited,
    })),
  );
  return rules;
}

/**
 * Load rules from a nested ancestor directory (strictly below project root).
 * These are never unconditional: a no-paths rule becomes implicitly scoped
 * to the ancestor's subtree.
 */
export async function loadNestedRulesAt(
  ancestor: string,
  projectRoot: string,
  home: string | null,
): Promise<Rule[]> {
  return loadRulesFromRoot({
    baseDir: ancestor,
    globBase: ancestor,
    subtreeBase: ancestor,
    projectRoot,
    home,
    visited: new Set(),
  });
}

/**
 * Return the chain of ancestor directories from `accessedFile` up to (and
 * including) `projectRoot`. Returns empty array if the file is not under
 * projectRoot, so callers can skip nested rule lookups cleanly for
 * out-of-project accesses.
 */
export function walkUpAncestors(
  accessedFile: string,
  projectRoot: string,
): string[] {
  if (!isUnderDir(accessedFile, projectRoot)) return [];
  const out: string[] = [];
  let cur = path.dirname(accessedFile);
  for (let i = 0; i < MAX_WALK_UP; i++) {
    out.push(cur);
    if (cur === projectRoot) break;
    const parent = path.dirname(cur);
    if (parent === cur) break; // hit fs root
    cur = parent;
  }
  return out;
}

export function formatRuleBlock(rule: Rule, matched?: string): string {
  // Plain Markdown, NOT wrapped in <system-reminder>. Claude treats the
  // system-reminder tag as an ephemeral harness reminder (trained to not
  // surface its contents), which made rules invisible to the model even
  // though they were being pushed into output.system. Reference plugins
  // like clopca/open-mem use bare Markdown headers for the same reason.
  const header = matched
    ? `## Rule: ${rule.relPath} (applies to ${matched})`
    : `## Rule: ${rule.relPath}`;
  return `${header}\n\n${rule.body}`;
}

/**
 * Build the combined Markdown block for injection. Returns an empty string
 * when there is nothing to inject. Reference plugins (open-mem,
 * opencode-rules) push a SINGLE string to `output.system` rather than
 * multiple blocks; that keeps everything inside one `role: "system"`
 * message on the wire and bypasses OpenCode's rejoin heuristic.
 */
export function buildInjectionText(
  state: SessionState,
  rules: Rule[],
): { text: string; unconditionalCount: number; scopedCount: number } {
  // 1) Promote any queued accessed paths into activeScoped.
  if (state.pendingAccessedPaths.length > 0) {
    const pending = state.pendingAccessedPaths.splice(0);
    for (const accessed of pending) {
      for (const rule of rules) {
        if (!rule.matcher) continue;
        if (!rule.matcher(accessed)) continue;
        state.activeScoped.add(rule.realPath);
      }
    }
  }

  const byRealPath = new Map<string, Rule>(rules.map((r) => [r.realPath, r]));
  const parts: string[] = [];
  let unconditionalCount = 0;
  let scopedCount = 0;

  for (const rule of rules) {
    if (!rule.unconditional) continue;
    parts.push(formatRuleBlock(rule));
    unconditionalCount++;
  }

  for (const ruleRealPath of state.activeScoped) {
    const rule = byRealPath.get(ruleRealPath);
    if (!rule) continue;
    parts.push(formatRuleBlock(rule));
    scopedCount++;
  }

  if (parts.length === 0) {
    return { text: "", unconditionalCount, scopedCount };
  }

  const text = [
    "# Project Rules (claude-rules plugin)",
    "",
    "These are rule files loaded from `.claude/rules/` and `.opencode/rules/` directories for the current project. They are real instructions, not ephemeral reminders: apply them to your work as appropriate.",
    "",
    ...parts,
  ].join("\n\n");

  return { text, unconditionalCount, scopedCount };
}

// ---------------------------------------------------------------------------
// Module state + helpers used by the plugin factory
// ---------------------------------------------------------------------------

export const topLevelRuleCache = new Map<
  string,
  { loadedAt: number; rules: Rule[] }
>();
export const nestedRulesCache = new Map<
  string,
  { loadedAt: number; rules: Rule[] }
>();
export const sessions = new Map<string, SessionState>();
export const errorsSeen = new Set<string>();

const TAG = "[claude-rules]";

export function dbg(msg: string, extra?: unknown): void {
  if (!DEBUG) return;
  if (extra !== undefined) console.debug(TAG, msg, extra);
  else console.debug(TAG, msg);
}

export function info(msg: string): void {
  console.info(TAG, msg);
}

export function logOnce(label: string, e: unknown): void {
  const msg = (e as { message?: string })?.message ?? String(e);
  const key = `${label}::${msg}`;
  if (errorsSeen.has(key)) return;
  errorsSeen.add(key);
  console.warn(TAG, `${label} error:`, msg);
}

export function resolveProjectRoot(ctx: PluginContext): string {
  const raw = ctx.worktree || ctx.directory || process.cwd();
  try {
    return fs.realpathSync(raw);
  } catch {
    return raw;
  }
}

export function resolveHome(): string | null {
  try {
    return fs.realpathSync(os.homedir());
  } catch {
    try {
      return os.homedir();
    } catch {
      return null;
    }
  }
}

function topCacheKey(projectRoot: string, home: string | null): string {
  return `${projectRoot}::${home ?? ""}`;
}

export async function loadCachedTopLevelRules(
  projectRoot: string,
  home: string | null,
): Promise<Rule[]> {
  const now = Date.now();
  const key = topCacheKey(projectRoot, home);
  const cached = topLevelRuleCache.get(key);
  if (cached && now - cached.loadedAt < TTL_MS) return cached.rules;
  const rules = await loadTopLevelRules(projectRoot, home);
  topLevelRuleCache.set(key, { loadedAt: now, rules });
  dbg(`loaded ${rules.length} top-level rule(s) for ${projectRoot}`, {
    unconditional: rules.filter((r) => r.unconditional).map((r) => r.relPath),
    scoped: rules
      .filter((r) => !r.unconditional)
      .map((r) => ({ rule: r.relPath, paths: r.paths ?? null })),
  });
  return rules;
}

/**
 * Walk up from `accessedFile` to `projectRoot` and populate nestedRulesCache
 * for each ancestor that has `.claude/rules/` or `.opencode/rules/`. No-ops
 * for files outside the project subtree.
 */
export async function ensureNestedRulesForFile(
  accessedFile: string,
  projectRoot: string,
  home: string | null,
): Promise<void> {
  const now = Date.now();
  for (const ancestor of walkUpAncestors(accessedFile, projectRoot)) {
    if (ancestor === projectRoot) continue; // handled by top-level cache
    const cached = nestedRulesCache.get(ancestor);
    if (cached && now - cached.loadedAt < TTL_MS) continue;
    const rules = await loadNestedRulesAt(ancestor, projectRoot, home);
    nestedRulesCache.set(ancestor, { loadedAt: now, rules });
    if (rules.length > 0) {
      dbg(`discovered ${rules.length} nested rule(s) at ${ancestor}`, {
        rules: rules.map((r) => r.relPath),
      });
    }
  }
}

export function allKnownRules(
  projectRoot: string,
  home: string | null,
): Rule[] {
  // Dedupe by realPath so a rule file that happens to be discoverable via
  // multiple roots (symlinks, or top-level + nested reaching the same file)
  // only appears once in the injection pipeline. Top-level wins over nested
  // because it was inserted first; among nested, the deepest ancestor wins
  // (walk-up populates nestedRulesCache innermost-first).
  const out: Rule[] = [];
  const seen = new Set<string>();
  const top =
    topLevelRuleCache.get(topCacheKey(projectRoot, home))?.rules ?? [];
  for (const rule of top) {
    if (seen.has(rule.realPath)) continue;
    seen.add(rule.realPath);
    out.push(rule);
  }
  for (const entry of nestedRulesCache.values()) {
    for (const rule of entry.rules) {
      if (seen.has(rule.realPath)) continue;
      seen.add(rule.realPath);
      out.push(rule);
    }
  }
  return out;
}

export function ensureSession(sessionID: string): SessionState {
  let s = sessions.get(sessionID);
  if (!s) {
    while (sessions.size >= MAX_SESSIONS) {
      const firstKey = sessions.keys().next().value;
      if (firstKey === undefined) break;
      sessions.delete(firstKey);
    }
    s = newSessionState();
    sessions.set(sessionID, s);
  }
  return s;
}

export function __resetForTests(): void {
  topLevelRuleCache.clear();
  nestedRulesCache.clear();
  sessions.clear();
  errorsSeen.clear();
}
