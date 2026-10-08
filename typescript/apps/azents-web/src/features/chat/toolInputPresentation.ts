export interface ToolInputField {
  name: string;
  text: string;
}

export type ToolInputPresentation =
  { type: "fields"; fields: ToolInputField[] } | { type: "text"; text: string };

/** Indent validated JSON tokens without changing scalar lexemes. */
function formatTokens(tokens: readonly string[]): string {
  let depth = 0;
  let output = "";
  for (const [index, token] of tokens.entries()) {
    const previous = tokens[index - 1];
    const next = tokens[index + 1];
    if (token === "{" || token === "[") {
      output += token;
      if (next !== "}" && next !== "]") {
        depth += 1;
        output += `\n${"  ".repeat(depth)}`;
      }
    } else if (token === "}" || token === "]") {
      if (previous !== "{" && previous !== "[") {
        depth -= 1;
        output += `\n${"  ".repeat(depth)}`;
      }
      output += token;
    } else if (token === ",") {
      output += `,\n${"  ".repeat(depth)}`;
    } else if (token === ":") {
      output += ": ";
    } else {
      output += token;
    }
  }
  return output;
}

/** Decode arbitrary diagnostic input into display-only fields at the boundary. */
export function toolInputPresentation(input: string): ToolInputPresentation {
  try {
    const value: unknown = JSON.parse(input);
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return { type: "text", text: input };
    }
    // JSON.parse validates syntax; display values come from the retained tokens.
    const tokens =
      input.match(
        /"(?:\\[\s\S]|[^"\\])*"|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null|[{}[\],:]/g,
      ) ?? [];
    const fields: ToolInputField[] = [];
    let cursor = 1;
    while (cursor < tokens.length - 1) {
      const nameToken = tokens[cursor];
      if (typeof nameToken !== "string") {
        throw new Error("Missing tool input field name");
      }
      const name: unknown = JSON.parse(nameToken);
      if (typeof name !== "string") {
        throw new Error("Invalid tool input field name");
      }
      cursor += 2;
      const start = cursor;
      let depth = 0;
      while (cursor < tokens.length) {
        const token = tokens[cursor];
        if (depth === 0 && (token === "," || token === "}")) {
          break;
        }
        if (token === "{" || token === "[") {
          depth += 1;
        } else if (token === "}" || token === "]") {
          depth -= 1;
        }
        cursor += 1;
      }
      const fieldTokens = tokens.slice(start, cursor);
      const first = fieldTokens[0];
      const decoded: unknown =
        fieldTokens.length === 1 && first?.startsWith('"')
          ? JSON.parse(first)
          : null;
      fields.push({
        name,
        text:
          typeof decoded === "string" && decoded.length > 0
            ? decoded
            : formatTokens(fieldTokens),
      });
      cursor += 1;
    }
    return { type: "fields", fields };
  } catch {
    return { type: "text", text: input };
  }
}
