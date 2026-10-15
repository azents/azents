export type V4APatchLine =
  | { type: "context"; content: string }
  | { type: "add"; content: string }
  | { type: "remove"; content: string };

export interface V4APatchHunk {
  context: string | null;
  lines: V4APatchLine[];
}

export type V4APatchFile =
  | { type: "add"; path: string; lines: string[] }
  | { type: "delete"; path: string }
  | {
      type: "update";
      path: string;
      moveTo: string | null;
      hunks: V4APatchHunk[];
    };

export interface V4APatchPresentation {
  files: V4APatchFile[];
}

function pathAfterHeader(line: string, header: string): string | null {
  const path = line.slice(header.length).trim();
  return path.length > 0 ? path : null;
}

function patchLine(line: string): V4APatchLine | null {
  if (line.startsWith(" ")) {
    return { type: "context", content: line.slice(1) };
  }
  if (line.startsWith("+")) {
    return { type: "add", content: line.slice(1) };
  }
  if (line.startsWith("-")) {
    return { type: "remove", content: line.slice(1) };
  }
  return null;
}

function isFileOperationHeader(line: string): boolean {
  return (
    line.startsWith("*** Add File: ") ||
    line.startsWith("*** Delete File: ") ||
    line.startsWith("*** Update File: ")
  );
}

function normalizedLines(value: string): string[] {
  const lines = value.split(/\r?\n/);
  if (lines.at(-1) === "") {
    lines.pop();
  }
  return lines;
}

/** Parse a strict V4A patch into independent, display-safe file operations. */
export function parseV4APatch(value: string): V4APatchPresentation | null {
  const lines = normalizedLines(value);
  if (
    lines.length < 2 ||
    lines[0] !== "*** Begin Patch" ||
    lines.at(-1) !== "*** End Patch"
  ) {
    return null;
  }

  const files: V4APatchFile[] = [];
  let index = 1;
  const endIndex = lines.length - 1;
  while (index < endIndex) {
    const header = lines[index];
    if (typeof header !== "string") {
      return null;
    }
    if (header.startsWith("*** Add File: ")) {
      const path = pathAfterHeader(header, "*** Add File: ");
      if (path === null) {
        return null;
      }
      index += 1;
      const addedLines: string[] = [];
      while (index < endIndex) {
        const line = lines[index];
        if (typeof line !== "string") {
          return null;
        }
        if (isFileOperationHeader(line)) {
          break;
        }
        if (!line.startsWith("+")) {
          return null;
        }
        addedLines.push(line.slice(1));
        index += 1;
      }
      files.push({ type: "add", path, lines: addedLines });
      continue;
    }

    if (header.startsWith("*** Delete File: ")) {
      const path = pathAfterHeader(header, "*** Delete File: ");
      if (path === null) {
        return null;
      }
      index += 1;
      files.push({ type: "delete", path });
      continue;
    }

    if (header.startsWith("*** Update File: ")) {
      const path = pathAfterHeader(header, "*** Update File: ");
      if (path === null) {
        return null;
      }
      index += 1;
      let moveTo: string | null = null;
      const moveHeader = lines[index];
      if (moveHeader?.startsWith("*** Move to: ")) {
        moveTo = pathAfterHeader(moveHeader, "*** Move to: ");
        if (moveTo === null) {
          return null;
        }
        index += 1;
      }
      const hunks: V4APatchHunk[] = [];
      while (index < endIndex) {
        const hunkHeader = lines[index];
        if (typeof hunkHeader !== "string") {
          return null;
        }
        if (isFileOperationHeader(hunkHeader)) {
          break;
        }
        if (hunkHeader !== "@@" && !hunkHeader.startsWith("@@ ")) {
          return null;
        }
        const context = hunkHeader.length === 2 ? null : hunkHeader.slice(3);
        index += 1;
        const hunkLines: V4APatchLine[] = [];
        while (index < endIndex) {
          const line = lines[index];
          if (typeof line !== "string") {
            return null;
          }
          if (line === "*** End of File") {
            index += 1;
            break;
          }
          if (
            isFileOperationHeader(line) ||
            line === "@@" ||
            line.startsWith("@@ ")
          ) {
            break;
          }
          const parsed = patchLine(line);
          if (parsed === null) {
            return null;
          }
          hunkLines.push(parsed);
          index += 1;
        }
        if (hunkLines.length === 0) {
          return null;
        }
        hunks.push({ context, lines: hunkLines });
      }
      if (hunks.length === 0) {
        return null;
      }
      files.push({ type: "update", path, moveTo, hunks });
      continue;
    }

    return null;
  }

  return files.length > 0 ? { files } : null;
}
