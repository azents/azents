import { toolkitSourceFromValue } from "./toolCallMerge.ts";
import type { ActiveToolCall, DelegatedToolSnapshot } from "./types.ts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function delegatedToolFromValue(
  value: unknown,
): DelegatedToolSnapshot | null {
  if (
    !isRecord(value) ||
    typeof value.name !== "string" ||
    value.name.length === 0 ||
    value.name === "run_tool_to_file" ||
    (value.wire_dialect !== "json_function" &&
      value.wire_dialect !== "plaintext_custom")
  ) {
    return null;
  }
  return {
    name: value.name,
    wireDialect: value.wire_dialect,
    toolkitSource: toolkitSourceFromValue(value.toolkit_source) ?? null,
  };
}

interface DelegatedInput {
  name: string;
  arguments: string;
}

function delegatedInput(text: string): DelegatedInput | null {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return null;
  }
  if (
    !isRecord(value) ||
    typeof value.tool_name !== "string" ||
    value.tool_name.length === 0 ||
    value.tool_name === "run_tool_to_file" ||
    typeof value.arguments !== "string"
  ) {
    return null;
  }
  return { name: value.tool_name, arguments: value.arguments };
}

/** Project display fields only; callers retain the original wrapper for Raw data. */
export function toolCallForDisplay(toolCall: ActiveToolCall): ActiveToolCall {
  if (toolCall.name !== "run_tool_to_file") {
    return toolCall;
  }
  const input = delegatedInput(toolCall.arguments);
  if (input === null) {
    return toolCall;
  }
  const snapshot = toolCall.delegatedTool;
  if (
    snapshot === null ||
    typeof snapshot === "undefined" ||
    snapshot.name !== input.name
  ) {
    return toolCall;
  }
  const result = toolCall.resultMetadata?.delegated_result;
  const output =
    isRecord(result) && typeof result.output === "string"
      ? result.output
      : undefined;
  const metadata =
    isRecord(result) && isRecord(result.metadata) ? result.metadata : undefined;
  return {
    ...toolCall,
    name: snapshot.name,
    arguments: input.arguments,
    wireDialect: snapshot.wireDialect,
    toolkitSource: snapshot.toolkitSource,
    result: output ?? toolCall.result,
    resultMetadata: metadata,
    delegatedTool: null,
  };
}

export type OutputFileState = "pending" | "stored" | "partial" | "failed";

export function outputFileState(
  toolCall: ActiveToolCall,
): OutputFileState | null {
  if (toolCall.name !== "run_tool_to_file") {
    return null;
  }
  if (toolCall.status === "running" || toolCall.status === "preparing") {
    return "pending";
  }
  if (toolCall.status !== "completed") {
    return "failed";
  }
  return toolCall.resultMetadata?.failed_part_count === 0 &&
    toolCall.resultMetadata.manifest_stored === true
    ? "stored"
    : "partial";
}
