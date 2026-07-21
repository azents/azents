import { z } from "zod";
import { parseV4APatch } from "./v4aPatchPresentation.ts";
import type { ActiveToolCall } from "./types";
import type { V4APatchFile } from "./v4aPatchPresentation.ts";

export type KnownToolPresentationReason =
  | "unregistered"
  | "unsupported-phase"
  | "invalid-arguments"
  | "invalid-output"
  | "adapter-error";

export type KnownToolAction =
  | "read"
  | "search"
  | "list"
  | "write"
  | "edit"
  | "patch"
  | "delete"
  | "command"
  | "process"
  | "present";

export interface OutputDetail {
  type: "output";
  output: string;
}

export interface DiffDetail {
  type: "diff";
  file: V4APatchFile;
}

export interface PatchDetail {
  type: "patch";
  files: V4APatchFile[];
}

export interface ProcessDetail {
  type: "process";
  command: string | null;
  exitCode: number | null;
  truncated: boolean;
  output: string;
}

export type KnownToolDetail =
  | OutputDetail
  | DiffDetail
  | PatchDetail
  | ProcessDetail
  | null;

export interface KnownToolPresentation {
  action: KnownToolAction;
  subject: string | null;
  qualifier: string | null;
  detail: KnownToolDetail;
}

export type KnownToolPresentationResult =
  | { type: "specialized"; presentation: KnownToolPresentation }
  | { type: "generic"; reason: KnownToolPresentationReason };

const pathInputSchema = z.object({ path: z.string().min(1) });
const readInputSchema = pathInputSchema.extend({
  offset: z.number().int().nonnegative().optional(),
  limit: z.number().int().positive().optional(),
});
const grepInputSchema = z.object({
  pattern: z.string().min(1),
  path: z.string().min(1),
});
const globInputSchema = z.object({ pattern: z.string().min(1) });
const writeInputSchema = pathInputSchema.extend({ content: z.string() });
const editInputSchema = pathInputSchema.extend({
  old_string: z.string(),
  new_string: z.string(),
});
const applyPatchInputSchema = z.object({
  base_path: z.string().min(1),
  patch: z.string().min(1),
});
const execCommandInputSchema = z.object({ command: z.string().min(1) });
const writeStdinInputSchema = z.object({ process_id: z.string().min(1) });
const presentFileInputSchema = z.object({
  paths: z.array(z.string().min(1)).min(1),
});
const patchChangeSchema = z.object({
  action: z.union([z.literal("add"), z.literal("update"), z.literal("delete")]),
  added_lines: z.number().int().nonnegative(),
  path: z.string().min(1),
  removed_lines: z.number().int().nonnegative(),
});
const applyPatchResultSchema = z.object({
  kind: z.literal("apply_patch_result"),
  changes: z.array(patchChangeSchema),
});
const applyPatchFailureSchema = z.object({
  kind: z.literal("apply_patch_failure"),
  applied: z.array(patchChangeSchema),
});
const processResultSchema = z.object({
  exit_code: z.number().int().nullable(),
  kind: z.union([
    z.literal("exec_command_result"),
    z.literal("write_stdin_result"),
  ]),
  status: z.string().min(1),
  stderr_truncated: z.boolean(),
  stdout_truncated: z.boolean(),
});
const MAX_SUBJECT_LENGTH = 96;

function parsedArguments(
  value: string,
): { success: true; value: unknown } | { success: false } {
  try {
    return { success: true, value: JSON.parse(value) };
  } catch {
    return { success: false };
  }
}

function displayPath(path: string): string {
  const oneLinePath = path
    .replace(/[\u0000-\u001F\u007F]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const workspacePrefix = "/workspace/agent/";
  const subject = oneLinePath.startsWith(workspacePrefix)
    ? oneLinePath.slice(workspacePrefix.length)
    : (oneLinePath
        .split("/")
        .filter((segment) => segment.length > 0)
        .at(-1) ?? oneLinePath);
  if (subject.length <= MAX_SUBJECT_LENGTH) {
    return subject;
  }
  return `${subject.slice(0, MAX_SUBJECT_LENGTH - 1)}…`;
}

function outputDetail(toolCall: ActiveToolCall): KnownToolDetail {
  if (toolCall.status === "running") {
    return null;
  }
  return typeof toolCall.result === "string" && toolCall.result.length > 0
    ? { type: "output", output: toolCall.result }
    : null;
}

function editDiff(
  path: string,
  oldValue: string,
  newValue: string,
): V4APatchFile {
  return {
    type: "update",
    path: displayPath(path),
    moveTo: null,
    hunks: [
      {
        context: null,
        lines: [
          ...oldValue
            .split("\n")
            .map((content) => ({ type: "remove" as const, content })),
          ...newValue
            .split("\n")
            .map((content) => ({ type: "add" as const, content })),
        ],
      },
    ],
  };
}

function terminal(toolCall: ActiveToolCall): boolean {
  return toolCall.status !== "running" && toolCall.status !== "preparing";
}

function generic(
  reason: KnownToolPresentationReason,
): KnownToolPresentationResult {
  return { type: "generic", reason };
}

function presentation(
  action: KnownToolAction,
  subject: string | null,
  qualifier: string | null,
  detail: KnownToolDetail,
): KnownToolPresentationResult {
  return {
    type: "specialized",
    presentation: { action, subject, qualifier, detail },
  };
}

function patchPresentation(
  toolCall: ActiveToolCall,
  input: z.infer<typeof applyPatchInputSchema>,
): KnownToolPresentationResult {
  const patch = parseV4APatch(input.patch);
  if (patch === null) {
    return generic("invalid-arguments");
  }
  if (!terminal(toolCall)) {
    return presentation("patch", displayPath(input.base_path), null, null);
  }
  const metadata = toolCall.resultMetadata;
  const success = applyPatchResultSchema.safeParse(metadata);
  if (success.success) {
    return presentation(
      "patch",
      displayPath(input.base_path),
      success.data.changes.length > 0
        ? String(success.data.changes.length)
        : null,
      { type: "patch", files: patch.files },
    );
  }
  const failure = applyPatchFailureSchema.safeParse(metadata);
  if (failure.success) {
    return presentation(
      "patch",
      displayPath(input.base_path),
      failure.data.applied.length > 0
        ? String(failure.data.applied.length)
        : null,
      failure.data.applied.length > 0
        ? { type: "patch", files: patch.files }
        : outputDetail(toolCall),
    );
  }
  return generic("invalid-output");
}

function processPresentation(
  toolCall: ActiveToolCall,
  action: "command" | "process",
  expectedKind: "exec_command_result" | "write_stdin_result",
  command: string | null,
): KnownToolPresentationResult {
  if (!terminal(toolCall)) {
    return presentation(
      action,
      null,
      null,
      command === null
        ? null
        : {
            type: "process",
            command,
            exitCode: null,
            truncated: false,
            output: "",
          },
    );
  }
  const metadata = processResultSchema.safeParse(toolCall.resultMetadata);
  if (!metadata.success) {
    return generic("invalid-output");
  }
  if (metadata.data.kind !== expectedKind) {
    return generic("invalid-output");
  }
  const output = toolCall.result ?? "";
  return presentation(
    action,
    null,
    metadata.data.exit_code === null ? null : String(metadata.data.exit_code),
    {
      type: "process",
      command,
      exitCode: metadata.data.exit_code,
      truncated:
        metadata.data.stdout_truncated || metadata.data.stderr_truncated,
      output,
    },
  );
}

export function knownToolPresentation(
  toolCall: ActiveToolCall,
): KnownToolPresentationResult {
  if (
    toolCall.toolkitSource !== null &&
    typeof toolCall.toolkitSource !== "undefined"
  ) {
    return generic("unregistered");
  }
  if (toolCall.status === "preparing") {
    return generic("unsupported-phase");
  }
  const argumentsResult = parsedArguments(toolCall.arguments);
  if (!argumentsResult.success) {
    return generic("invalid-arguments");
  }
  try {
    switch (toolCall.name) {
      case "read": {
        const input = readInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? presentation(
              "read",
              displayPath(input.data.path),
              input.data.offset && input.data.offset > 0
                ? String(input.data.offset)
                : null,
              outputDetail(toolCall),
            )
          : generic("invalid-arguments");
      }
      case "grep": {
        const input = grepInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? presentation(
              "search",
              displayPath(input.data.path),
              null,
              outputDetail(toolCall),
            )
          : generic("invalid-arguments");
      }
      case "glob": {
        const input = globInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? presentation(
              "list",
              displayPath(input.data.pattern),
              null,
              outputDetail(toolCall),
            )
          : generic("invalid-arguments");
      }
      case "write": {
        const input = writeInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? presentation("write", displayPath(input.data.path), null, null)
          : generic("invalid-arguments");
      }
      case "edit": {
        const input = editInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? presentation("edit", displayPath(input.data.path), null, {
              type: "diff",
              file: editDiff(
                input.data.path,
                input.data.old_string,
                input.data.new_string,
              ),
            })
          : generic("invalid-arguments");
      }
      case "apply_patch": {
        const input = applyPatchInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? patchPresentation(toolCall, input.data)
          : generic("invalid-arguments");
      }
      case "delete": {
        const input = pathInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? presentation("delete", displayPath(input.data.path), null, null)
          : generic("invalid-arguments");
      }
      case "exec_command": {
        const input = execCommandInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? processPresentation(
              toolCall,
              "command",
              "exec_command_result",
              input.data.command,
            )
          : generic("invalid-arguments");
      }
      case "write_stdin": {
        const input = writeStdinInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? processPresentation(toolCall, "process", "write_stdin_result", null)
          : generic("invalid-arguments");
      }
      case "present_file": {
        const input = presentFileInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        const firstPath = input.data.paths[0];
        return typeof firstPath !== "string"
          ? generic("invalid-arguments")
          : presentation("present", displayPath(firstPath), null, null);
      }
      default:
        return generic("unregistered");
    }
  } catch {
    return generic("adapter-error");
  }
}
