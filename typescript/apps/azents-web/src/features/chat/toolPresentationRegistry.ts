import { z } from "zod";
import type { ToolActivityCall } from "./toolActivityPresentation";
import type { FileAttachment } from "./types";

export type ToolActivityPhaseKind =
  | "inspection"
  | "execution"
  | "changes"
  | "generation"
  | "generic";

export interface ToolCallPresentation {
  type: "specialized" | "generic";
  phaseKind: ToolActivityPhaseKind;
  deliverables: FileAttachment[];
}

export interface ToolActivityPhase {
  id: string;
  kind: ToolActivityPhaseKind;
  calls: ToolActivityCall[];
}

const pathSchema = z.object({ path: z.string().min(1) }).passthrough();
const grepSchema = z
  .object({ pattern: z.string().min(1), path: z.string().min(1) })
  .passthrough();
const globSchema = z.object({ pattern: z.string().min(1) }).passthrough();
const commandSchema = z.object({ command: z.string().min(1) }).passthrough();
const writeStdinSchema = z
  .object({ process_id: z.string().min(1) })
  .passthrough();
const writeSchema = z
  .object({ path: z.string().min(1), content: z.string() })
  .passthrough();
const editSchema = z
  .object({
    path: z.string().min(1),
    old_string: z.string(),
    new_string: z.string(),
  })
  .passthrough();
const imageGenerationSchema = z
  .object({ prompt: z.string().min(1) })
  .passthrough();
const providerSearchSchema = z
  .object({ query: z.string().min(1).optional() })
  .passthrough();
const providerCodeSchema = z.object({}).passthrough();

function normalizedToolName(name: string): string {
  return name.startsWith("functions.") ? name.slice("functions.".length) : name;
}

function parsedArguments(
  argumentsValue: string,
): { success: true; value: unknown } | { success: false } {
  if (argumentsValue.trim().length === 0) {
    return { success: true, value: {} };
  }
  try {
    return { success: true, value: JSON.parse(argumentsValue) };
  } catch {
    return { success: false };
  }
}

function hasKnownOutputShape(call: ToolActivityCall): boolean {
  if (call.toolCall.status === "running") {
    return true;
  }
  if (call.type === "client" && call.toolCall.status === "preparing") {
    return true;
  }
  const output =
    call.type === "client" ? call.toolCall.result : call.toolCall.output;
  return typeof output === "string";
}

function imageDeliverables(call: ToolActivityCall): FileAttachment[] {
  if (call.toolCall.status !== "completed") {
    return [];
  }
  return (call.toolCall.attachments ?? []).filter((attachment) =>
    attachment.mediaType.startsWith("image/"),
  );
}

function specialized(
  phaseKind: Exclude<ToolActivityPhaseKind, "generic">,
  deliverables: FileAttachment[] = [],
): ToolCallPresentation {
  return { type: "specialized", phaseKind, deliverables };
}

function generic(): ToolCallPresentation {
  return { type: "generic", phaseKind: "generic", deliverables: [] };
}

export function toolCallPresentation(
  call: ToolActivityCall,
): ToolCallPresentation {
  try {
    if (!hasKnownOutputShape(call)) {
      return generic();
    }

    const parsed = parsedArguments(call.toolCall.arguments);
    if (!parsed.success) {
      return generic();
    }
    const args = parsed.value;

    const name = normalizedToolName(call.toolCall.name);
    if (call.type === "provider") {
      switch (name) {
        case "web_search":
        case "file_search":
          return providerSearchSchema.safeParse(args).success
            ? specialized("inspection")
            : generic();
        case "code_interpreter":
          return providerCodeSchema.safeParse(args).success
            ? specialized("execution")
            : generic();
        case "image_generation":
          return imageGenerationSchema.safeParse(args).success
            ? specialized("generation", imageDeliverables(call))
            : generic();
        default:
          return generic();
      }
    }

    switch (name) {
      case "read":
        return pathSchema.safeParse(args).success
          ? specialized("inspection")
          : generic();
      case "grep":
        return grepSchema.safeParse(args).success
          ? specialized("inspection")
          : generic();
      case "glob":
        return globSchema.safeParse(args).success
          ? specialized("inspection")
          : generic();
      case "exec_command":
        return commandSchema.safeParse(args).success
          ? specialized("execution")
          : generic();
      case "write_stdin":
        return writeStdinSchema.safeParse(args).success
          ? specialized("execution")
          : generic();
      case "write":
        return writeSchema.safeParse(args).success
          ? specialized("changes")
          : generic();
      case "edit":
        return editSchema.safeParse(args).success
          ? specialized("changes")
          : generic();
      case "image_generation":
        return imageGenerationSchema.safeParse(args).success
          ? specialized("generation", imageDeliverables(call))
          : generic();
      default:
        return generic();
    }
  } catch {
    return generic();
  }
}

export function groupToolActivityPhases(
  calls: ToolActivityCall[],
): ToolActivityPhase[] {
  const phases: ToolActivityPhase[] = [];

  for (const call of calls) {
    const presentation = toolCallPresentation(call);
    const previous = phases.at(-1);
    if (previous?.kind === presentation.phaseKind) {
      previous.calls.push(call);
      continue;
    }
    phases.push({
      id: `${call.type}:${call.toolCall.callId ?? call.toolCall.id}`,
      kind: presentation.phaseKind,
      calls: [call],
    });
  }

  return phases;
}
