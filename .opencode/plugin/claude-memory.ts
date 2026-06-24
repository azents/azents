/**
 * claude-memory: Claude Code 의 파일 기반 메모리 시스템을 OpenCode 에서 그대로
 * 쓰도록 하는 plugin. Claude Code 와 같은 디렉토리/포맷을 공유하므로 같은
 * 레포에서 두 IDE 가 메모리를 주고받는다.
 *
 * 메모리 위치 결정 (모든 worktree 가 레포 단위 메모리를 공유):
 *   1. `CLAUDE_MEMORY_ROOT` 환경변수 — 명시 지정시 그 경로 사용.
 *   2. `git rev-parse --git-common-dir` 결과:
 *      - `.../.git` 으로 끝나면 그 부모 = main worktree 경로 (일반 레포).
 *      - 그 외 (bare repo, e.g. `xxx.git`): common-dir 자체를 anchor 로 사용
 *        → 같은 bare 의 모든 linked worktree 가 한 곳을 공유.
 *   3. git 밖이면 cwd fallback.
 *
 * 슬러그: 절대경로의 `/` → `-` (Claude Code 와 동일).
 *   예: `/home/code/repos/x` → `-home-code-repos-x`
 *
 * 디렉토리 구조: `~/.claude/projects/{slug}/memory/`
 *   - `MEMORY.md`: 인덱스 (`- [Title](file.md) — hook`)
 *   - 개별 메모리: `*.md` (frontmatter `name`/`description`/`type`)
 *
 * 동작:
 *   - `experimental.chat.system.transform` 으로 매 요청마다 MEMORY.md 내용을
 *     system prompt 에 주입 (200줄 후 truncate, Claude Code 와 동일).
 *   - 메모리가 없으면 디렉토리 위치 + 저장 포맷 안내만 주입.
 *
 * 도구는 등록하지 않는다 — 에이전트는 기존 Read/Write/Edit 로 메모리 파일을
 * 다룬다. 저장 절차는 codingbot agent prompt 의 Memory 섹션이 명시.
 */

import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const MAX_INDEX_LINES = 200;
const DEBUG = process.env.CLAUDE_MEMORY_DEBUG === "1";

interface PluginContext {
  worktree?: string;
  directory?: string;
}

const dbg = (...args: unknown[]) => {
  if (DEBUG) console.log("[claude-memory]", ...args);
};

const resolveMemoryRoot = (ctx: PluginContext): string => {
  const envRoot = process.env.CLAUDE_MEMORY_ROOT;
  if (envRoot && envRoot.length > 0) return envRoot;

  const cwd = ctx.worktree ?? ctx.directory ?? process.cwd();

  // Linked worktree → main worktree 로 통일.
  // `git rev-parse --git-common-dir` 는 main worktree 의 `.git` 디렉토리를
  // 가리킨다 (bare repo 면 bare 디렉토리 자체). `/.git` 으로 끝나면 그
  // 부모가 main worktree 의 작업 트리 루트.
  let commonDir: string;
  try {
    commonDir = execFileSync("git", ["rev-parse", "--git-common-dir"], {
      cwd,
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return cwd;
  }
  const absCommon = path.isAbsolute(commonDir)
    ? commonDir
    : path.resolve(cwd, commonDir);
  if (absCommon.endsWith(`${path.sep}.git`)) {
    return path.dirname(absCommon);
  }
  // bare repo (`xxx.git`). common-dir 자체를 anchor 로 → 같은 bare 의 모든
  // worktree 가 한 메모리를 공유한다.
  return absCommon;
};

const projectSlug = (root: string): string => {
  // Claude Code: 절대 경로의 `/` → `-`. 예: `/home/code/x` → `-home-code-x`.
  return root.replace(/\//g, "-");
};

const memoryDir = (root: string): string => {
  return path.join(
    os.homedir(),
    ".claude",
    "projects",
    projectSlug(root),
    "memory",
  );
};

const readIndex = (dir: string): string | null => {
  const indexPath = path.join(dir, "MEMORY.md");
  if (!fs.existsSync(indexPath)) return null;
  const content = fs.readFileSync(indexPath, "utf-8");
  const lines = content.split("\n");
  if (lines.length > MAX_INDEX_LINES) {
    return lines.slice(0, MAX_INDEX_LINES).join("\n") + "\n... (truncated)";
  }
  return content;
};

const buildInjection = (root: string): string => {
  const dir = memoryDir(root);
  const index = readIndex(dir);
  const header = "# Memory (Claude Code compatible)";
  const dirLine = `Memory directory: \`${dir}\``;
  const formatGuide = [
    "Save format:",
    "1. Write `<dir>/<slug>.md` with frontmatter:",
    "   ```",
    "   ---",
    "   name: <short title>",
    "   description: <one-line, used to decide future relevance>",
    "   type: user | feedback | project | reference",
    "   ---",
    "   <body>",
    "   ```",
    "2. Add a one-line entry to `<dir>/MEMORY.md`:",
    "   `- [Title](file.md) — one-line hook`",
  ].join("\n");

  if (index === null) {
    return [
      header,
      dirLine,
      "(empty — no MEMORY.md yet)",
      "",
      formatGuide,
    ].join("\n");
  }

  return [header, dirLine, "", index, "", formatGuide].join("\n");
};

export const ClaudeMemoryPlugin = async (ctx: PluginContext) => {
  const root = resolveMemoryRoot(ctx);
  dbg("loaded for", root, "→", memoryDir(root));

  return {
    "experimental.chat.system.transform": async (
      _input: { sessionID?: string },
      output: { system: string[] },
    ) => {
      const text = buildInjection(root);
      if (output.system.length > 0) {
        output.system[0] = `${output.system[0]}\n\n${text}`;
      } else {
        output.system.push(text);
      }
      dbg("injected bytes=", text.length);
      return output;
    },
  };
};
