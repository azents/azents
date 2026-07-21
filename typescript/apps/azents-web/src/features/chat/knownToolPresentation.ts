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
  | "grep"
  | "glob"
  | "write"
  | "edit"
  | "patch"
  | "delete"
  | "command"
  | "process"
  | "present"
  | "readImage"
  | "importFile"
  | "saveMemory"
  | "listMemories"
  | "getMemory"
  | "searchMemories"
  | "deleteMemory"
  | "getGoal"
  | "createGoal"
  | "updateGoal"
  | "updateTodo"
  | "loadSkill"
  | "spawnAgent"
  | "sendMessage"
  | "followupTask"
  | "waitAgent"
  | "interruptAgent"
  | "listAgents"
  | "toolSearch";

export type KnownToolDetailLabel =
  | "source"
  | "destination"
  | "overwrite"
  | "temporary"
  | "scope"
  | "type"
  | "description"
  | "query"
  | "result"
  | "objective"
  | "status"
  | "createdAt"
  | "updatedAt"
  | "operation"
  | "items"
  | "skill"
  | "task"
  | "message"
  | "agentPath"
  | "forkTurns"
  | "modelTarget"
  | "reasoningEffort"
  | "timeout"
  | "previousStatus"
  | "requestedLimit"
  | "activationLimit";

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

export interface SemanticField {
  label: KnownToolDetailLabel;
  value: string;
}

export interface SemanticSection {
  label: KnownToolDetailLabel;
  content: string;
}

export interface SemanticItem {
  title: string;
  subtitle: string | null;
  content: string | null;
}

export interface SemanticDetail {
  type: "semantic";
  fields: SemanticField[];
  sections: SemanticSection[];
  items: SemanticItem[];
}

export interface SkillDetail {
  type: "skill";
  content: string;
}

export type KnownToolDetail =
  | OutputDetail
  | DiffDetail
  | PatchDetail
  | ProcessDetail
  | SemanticDetail
  | SkillDetail
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

const scopeSchema = z.union([z.literal("agent"), z.literal("user")]);
const emptyInputSchema = z.object({}).strict();
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
const importFileInputSchema = z.object({
  uri: z.string().min(1),
  path: z.string().min(1).nullable().optional(),
  overwrite: z.boolean().optional(),
});
const saveMemoryInputSchema = z.object({
  scope: scopeSchema,
  type: z.string().min(1),
  name: z.string().min(1),
  description: z.string(),
  content: z.string(),
});
const listMemoriesInputSchema = z.object({
  scope: scopeSchema.nullable().optional(),
  type: z.string().min(1).nullable().optional(),
});
const namedMemoryInputSchema = z.object({
  scope: scopeSchema,
  name: z.string().min(1),
});
const searchMemoriesInputSchema = z.object({
  query: z.string().min(1),
  scope: scopeSchema.nullable().optional(),
});
const createGoalInputSchema = z.object({ objective: z.string().min(1) });
const updateGoalInputSchema = z.object({
  status: z.union([z.literal("complete"), z.literal("blocked")]),
});
const todoItemSchema = z.object({
  content: z.string().min(1),
  status: z.union([
    z.literal("pending"),
    z.literal("in_progress"),
    z.literal("completed"),
  ]),
});
const updateTodoInputSchema = z.object({
  operation: z.union([z.literal("replace"), z.literal("clear")]),
  items: z.array(todoItemSchema).optional(),
});
const loadSkillInputSchema = z.object({ skill_path: z.string().min(1) });
const spawnAgentInputSchema = z.object({
  name: z.string().min(1),
  task: z.string().min(1),
  agent_type: z.literal("default").optional(),
  fork_turns: z.string().min(1).optional(),
  model_target_label: z.string().min(1).nullable().optional(),
  reasoning_effort: z.string().min(1).nullable().optional(),
});
const sendMessageInputSchema = z.object({
  agent_name: z.string().min(1),
  message: z.string().min(1),
});
const followupTaskInputSchema = z.object({
  agent_name: z.string().min(1),
  task: z.string().min(1),
});
const waitAgentInputSchema = z.object({
  timeout_seconds: z.number().int().min(0).max(600).optional(),
});
const interruptAgentInputSchema = z.object({ agent_name: z.string().min(1) });
const toolSearchInputSchema = z.object({
  query: z.string().min(1),
  limit: z.number().int().min(1).max(10).optional(),
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
const memoryMutationResultSchema = z.object({
  status: z.union([z.literal("saved"), z.literal("deleted")]),
  name: z.string().min(1),
  scope: scopeSchema,
  type: z.string().min(1).optional(),
});
const goalStateSchema = z.object({
  objective: z.string().nullable(),
  status: z
    .union([
      z.literal("active"),
      z.literal("paused"),
      z.literal("blocked"),
      z.literal("complete"),
    ])
    .nullable(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
});
const agentResultSchema = z.object({
  status: z.string().min(1),
  agent_name: z.string().min(1),
  agent_path: z.string().min(1).optional(),
});
const waitResultSchema = z.object({
  message: z.string().min(1),
  timed_out: z.boolean(),
});
const interruptResultSchema = z.object({ previous_status: z.string().min(1) });
const agentListResultSchema = z.object({
  agents: z.array(
    z.object({
      agent_name: z.string().min(1),
      agent_path: z.string().min(1),
      agent_status: z.string().min(1),
      last_task_message: z.string().nullable(),
    }),
  ),
});
const toolSearchResultSchema = z.object({
  activated_tools: z.array(
    z.object({
      name: z.string().min(1),
      description: z.string(),
      source: z.string().min(1),
    }),
  ),
  requested_limit: z.number().int().positive(),
  activation_limit: z.number().int().nonnegative().nullable(),
  limit_reduced: z.boolean(),
});
const skillMetadataSchema = z.object({
  name: z.string().min(1),
  slug: z.string().min(1),
});

function parsedJson(
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
  return (
    oneLinePath
      .split("/")
      .filter((segment) => segment.length > 0)
      .at(-1) ?? oneLinePath
  );
}

function detailPath(path: string): string {
  return path
    .replace(/[\u0000-\u001F\u007F]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function sourceKind(uri: string): string {
  const separator = uri.indexOf("://");
  return separator > 0 ? uri.slice(0, separator) : "file";
}

function skillName(path: string): string {
  const segments = detailPath(path).split("/").filter(Boolean);
  return segments.at(-1) === "SKILL.md"
    ? (segments.at(-2) ?? "Skill")
    : (segments.at(-1) ?? "Skill");
}

function outputDetail(toolCall: ActiveToolCall): KnownToolDetail {
  if (toolCall.status === "running") {
    return null;
  }
  return typeof toolCall.result === "string" && toolCall.result.length > 0
    ? { type: "output", output: toolCall.result }
    : null;
}

function semanticDetail({
  fields = [],
  sections = [],
  items = [],
}: {
  fields?: SemanticField[];
  sections?: SemanticSection[];
  items?: SemanticItem[];
}): SemanticDetail | null {
  return fields.length > 0 || sections.length > 0 || items.length > 0
    ? { type: "semantic", fields, sections, items }
    : null;
}

function editDiff(
  path: string,
  oldValue: string,
  newValue: string,
): V4APatchFile {
  return {
    type: "update",
    path: detailPath(path),
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

function completed(toolCall: ActiveToolCall): boolean {
  return toolCall.status === "completed";
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

function parsedResult<T extends z.ZodTypeAny>(
  toolCall: ActiveToolCall,
  schema: T,
): z.infer<T> | null {
  if (typeof toolCall.result !== "string") {
    return null;
  }
  const parsed = parsedJson(toolCall.result);
  if (!parsed.success) {
    return null;
  }
  const validated = schema.safeParse(parsed.value);
  return validated.success ? validated.data : null;
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
  if (!metadata.success || metadata.data.kind !== expectedKind) {
    return generic("invalid-output");
  }
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
      output: toolCall.result ?? "",
    },
  );
}

function goalPresentation(
  toolCall: ActiveToolCall,
  action: "getGoal" | "createGoal" | "updateGoal",
  objective: string | null,
  requestedStatus: string | null,
): KnownToolPresentationResult {
  if (!completed(toolCall)) {
    return presentation(action, null, requestedStatus, outputDetail(toolCall));
  }
  const state = parsedResult(toolCall, goalStateSchema);
  if (state === null) {
    return generic("invalid-output");
  }
  const fields: SemanticField[] = [];
  if (state.status !== null) {
    fields.push({ label: "status", value: state.status });
  }
  if (state.created_at !== null) {
    fields.push({ label: "createdAt", value: state.created_at });
  }
  if (state.updated_at !== null) {
    fields.push({ label: "updatedAt", value: state.updated_at });
  }
  const resolvedObjective = state.objective ?? objective;
  return presentation(
    action,
    null,
    state.status ?? requestedStatus,
    semanticDetail({
      fields,
      sections:
        resolvedObjective === null
          ? []
          : [{ label: "objective", content: resolvedObjective }],
    }),
  );
}

function skillResult(
  result: string,
): { metadata: z.infer<typeof skillMetadataSchema>; content: string } | null {
  const match =
    /^Skill loaded from the active projection\.\nMetadata: (\{.*\})\n\n([\s\S]*)$/u.exec(
      result,
    );
  if (match === null) {
    return null;
  }
  const metadataText = match[1];
  const content = match[2];
  if (typeof metadataText !== "string" || typeof content !== "string") {
    return null;
  }
  const parsed = parsedJson(metadataText);
  if (!parsed.success) {
    return null;
  }
  const metadata = skillMetadataSchema.safeParse(parsed.value);
  return metadata.success ? { metadata: metadata.data, content } : null;
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
  const argumentsResult = parsedJson(toolCall.arguments);
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
              "grep",
              displayPath(input.data.path),
              null,
              semanticDetail({
                fields: [
                  { label: "query", value: input.data.pattern },
                  { label: "source", value: detailPath(input.data.path) },
                ],
                sections:
                  typeof toolCall.result === "string" && terminal(toolCall)
                    ? [{ label: "result", content: toolCall.result }]
                    : [],
              }),
            )
          : generic("invalid-arguments");
      }
      case "glob": {
        const input = globInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? presentation(
              "glob",
              null,
              null,
              semanticDetail({
                fields: [{ label: "query", value: input.data.pattern }],
                sections:
                  typeof toolCall.result === "string" && terminal(toolCall)
                    ? [{ label: "result", content: toolCall.result }]
                    : [],
              }),
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
        const firstPath = input.success ? (input.data.paths[0] ?? null) : null;
        return typeof firstPath === "string"
          ? presentation("present", displayPath(firstPath), null, null)
          : generic("invalid-arguments");
      }
      case "read_image": {
        const input = pathInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? presentation("readImage", displayPath(input.data.path), null, null)
          : generic("invalid-arguments");
      }
      case "import_file": {
        const input = importFileInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        const destination = input.data.path ?? null;
        return presentation(
          "importFile",
          destination === null ? null : displayPath(destination),
          null,
          semanticDetail({
            fields: [
              { label: "source", value: sourceKind(input.data.uri) },
              ...(destination === null
                ? []
                : [{ label: "destination" as const, value: destination }]),
              {
                label: "overwrite",
                value: String(input.data.overwrite ?? false),
              },
              ...(destination?.startsWith("/tmp/")
                ? [{ label: "temporary" as const, value: "true" }]
                : []),
            ],
          }),
        );
      }
      case "save_memory": {
        const input = saveMemoryInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        if (completed(toolCall)) {
          const result = parsedResult(toolCall, memoryMutationResultSchema);
          if (result === null || result.status !== "saved") {
            return generic("invalid-output");
          }
        }
        return presentation(
          "saveMemory",
          input.data.name,
          input.data.scope,
          semanticDetail({
            fields: [
              { label: "scope", value: input.data.scope },
              { label: "type", value: input.data.type },
              { label: "description", value: input.data.description },
            ],
          }),
        );
      }
      case "list_memories": {
        const input = listMemoriesInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? presentation(
              "listMemories",
              null,
              input.data.scope ?? input.data.type ?? null,
              typeof toolCall.result === "string" && terminal(toolCall)
                ? semanticDetail({
                    sections: [{ label: "result", content: toolCall.result }],
                  })
                : null,
            )
          : generic("invalid-arguments");
      }
      case "get_memory": {
        const input = namedMemoryInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? presentation(
              "getMemory",
              input.data.name,
              input.data.scope,
              typeof toolCall.result === "string" && terminal(toolCall)
                ? semanticDetail({
                    sections: [{ label: "result", content: toolCall.result }],
                  })
                : null,
            )
          : generic("invalid-arguments");
      }
      case "search_memories": {
        const input = searchMemoriesInputSchema.safeParse(
          argumentsResult.value,
        );
        return input.success
          ? presentation(
              "searchMemories",
              null,
              input.data.scope ?? null,
              semanticDetail({
                fields: [{ label: "query", value: input.data.query }],
                sections:
                  typeof toolCall.result === "string" && terminal(toolCall)
                    ? [{ label: "result", content: toolCall.result }]
                    : [],
              }),
            )
          : generic("invalid-arguments");
      }
      case "delete_memory": {
        const input = namedMemoryInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        if (completed(toolCall)) {
          const result = parsedResult(toolCall, memoryMutationResultSchema);
          if (result === null || result.status !== "deleted") {
            return generic("invalid-output");
          }
        }
        return presentation(
          "deleteMemory",
          input.data.name,
          input.data.scope,
          null,
        );
      }
      case "get_goal": {
        const input = emptyInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? goalPresentation(toolCall, "getGoal", null, null)
          : generic("invalid-arguments");
      }
      case "create_goal": {
        const input = createGoalInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? goalPresentation(
              toolCall,
              "createGoal",
              input.data.objective,
              "active",
            )
          : generic("invalid-arguments");
      }
      case "update_goal": {
        const input = updateGoalInputSchema.safeParse(argumentsResult.value);
        return input.success
          ? goalPresentation(toolCall, "updateGoal", null, input.data.status)
          : generic("invalid-arguments");
      }
      case "update_todo": {
        const input = updateTodoInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        if (completed(toolCall) && toolCall.result?.trim() !== "Done") {
          return generic("invalid-output");
        }
        const items =
          input.data.operation === "replace" ? (input.data.items ?? []) : [];
        return presentation(
          "updateTodo",
          null,
          input.data.operation === "clear" ? "clear" : String(items.length),
          semanticDetail({
            fields: [{ label: "operation", value: input.data.operation }],
            items: items.map((item) => ({
              title: item.content,
              subtitle: item.status,
              content: null,
            })),
          }),
        );
      }
      case "load_skill": {
        const input = loadSkillInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        if (!completed(toolCall)) {
          return presentation(
            "loadSkill",
            skillName(input.data.skill_path),
            null,
            outputDetail(toolCall),
          );
        }
        if (typeof toolCall.result !== "string") {
          return generic("invalid-output");
        }
        const result = skillResult(toolCall.result);
        return result === null
          ? generic("invalid-output")
          : presentation("loadSkill", result.metadata.name, null, {
              type: "skill",
              content: result.content,
            });
      }
      case "spawn_agent": {
        const input = spawnAgentInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        const result = completed(toolCall)
          ? parsedResult(toolCall, agentResultSchema)
          : null;
        if (completed(toolCall) && result === null) {
          return generic("invalid-output");
        }
        return presentation(
          "spawnAgent",
          input.data.name,
          result?.status ?? null,
          semanticDetail({
            fields: [
              { label: "forkTurns", value: input.data.fork_turns ?? "all" },
              ...(input.data.model_target_label
                ? [
                    {
                      label: "modelTarget" as const,
                      value: input.data.model_target_label,
                    },
                  ]
                : []),
              ...(input.data.reasoning_effort
                ? [
                    {
                      label: "reasoningEffort" as const,
                      value: input.data.reasoning_effort,
                    },
                  ]
                : []),
              ...(result?.agent_path
                ? [{ label: "agentPath" as const, value: result.agent_path }]
                : []),
            ],
            sections: [{ label: "task", content: input.data.task }],
          }),
        );
      }
      case "send_message": {
        const input = sendMessageInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        const result = completed(toolCall)
          ? parsedResult(toolCall, agentResultSchema)
          : null;
        if (completed(toolCall) && result === null) {
          return generic("invalid-output");
        }
        return presentation(
          "sendMessage",
          input.data.agent_name,
          result?.status ?? null,
          semanticDetail({
            fields: result?.agent_path
              ? [{ label: "agentPath", value: result.agent_path }]
              : [],
            sections: [{ label: "message", content: input.data.message }],
          }),
        );
      }
      case "followup_task": {
        const input = followupTaskInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        const result = completed(toolCall)
          ? parsedResult(toolCall, agentResultSchema)
          : null;
        if (completed(toolCall) && result === null) {
          return generic("invalid-output");
        }
        return presentation(
          "followupTask",
          input.data.agent_name,
          result?.status ?? null,
          semanticDetail({
            fields: result?.agent_path
              ? [{ label: "agentPath", value: result.agent_path }]
              : [],
            sections: [{ label: "task", content: input.data.task }],
          }),
        );
      }
      case "wait_agent": {
        const input = waitAgentInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        const result = completed(toolCall)
          ? parsedResult(toolCall, waitResultSchema)
          : null;
        if (completed(toolCall) && result === null) {
          return generic("invalid-output");
        }
        return presentation(
          "waitAgent",
          null,
          result === null ? null : result.timed_out ? "timed_out" : "complete",
          semanticDetail({
            fields: [
              {
                label: "timeout",
                value: String(input.data.timeout_seconds ?? 30),
              },
            ],
            sections:
              result === null
                ? []
                : [{ label: "result", content: result.message }],
          }),
        );
      }
      case "interrupt_agent": {
        const input = interruptAgentInputSchema.safeParse(
          argumentsResult.value,
        );
        if (!input.success) {
          return generic("invalid-arguments");
        }
        const result = completed(toolCall)
          ? parsedResult(toolCall, interruptResultSchema)
          : null;
        if (completed(toolCall) && result === null) {
          return generic("invalid-output");
        }
        return presentation(
          "interruptAgent",
          input.data.agent_name,
          result?.previous_status ?? null,
          result === null
            ? null
            : semanticDetail({
                fields: [
                  {
                    label: "previousStatus",
                    value: result.previous_status,
                  },
                ],
              }),
        );
      }
      case "list_agents": {
        const input = emptyInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        const result = completed(toolCall)
          ? parsedResult(toolCall, agentListResultSchema)
          : null;
        if (completed(toolCall) && result === null) {
          return generic("invalid-output");
        }
        return presentation(
          "listAgents",
          null,
          result === null ? null : String(result.agents.length),
          result === null
            ? null
            : semanticDetail({
                items: result.agents.map((agent) => ({
                  title: agent.agent_name,
                  subtitle: `${agent.agent_status} · ${agent.agent_path}`,
                  content: agent.last_task_message,
                })),
              }),
        );
      }
      case "tool_search": {
        const input = toolSearchInputSchema.safeParse(argumentsResult.value);
        if (!input.success) {
          return generic("invalid-arguments");
        }
        const result = completed(toolCall)
          ? parsedResult(toolCall, toolSearchResultSchema)
          : null;
        if (completed(toolCall) && result === null) {
          return generic("invalid-output");
        }
        return presentation(
          "toolSearch",
          null,
          result === null ? null : String(result.activated_tools.length),
          semanticDetail({
            fields: [
              { label: "query", value: input.data.query },
              {
                label: "requestedLimit",
                value: String(result?.requested_limit ?? input.data.limit ?? 5),
              },
              ...(result?.activation_limit === null ||
              typeof result?.activation_limit === "undefined"
                ? []
                : [
                    {
                      label: "activationLimit" as const,
                      value: String(result.activation_limit),
                    },
                  ]),
            ],
            items:
              result?.activated_tools.map((tool) => ({
                title: tool.name,
                subtitle: tool.source,
                content: tool.description,
              })) ?? [],
          }),
        );
      }
      default:
        return generic("unregistered");
    }
  } catch {
    return generic("adapter-error");
  }
}
