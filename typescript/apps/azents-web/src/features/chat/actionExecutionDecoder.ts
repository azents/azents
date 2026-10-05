import { z } from "zod";
import type {
  ActionExecutionProjection,
  ActionExecutionUpdatedEvent,
} from "./types";
import type {
  ActionExecutionProjectionResponse,
  ChatEventResponse,
} from "@azents/public-client";

const nonEmptyString = z.string().min(1);
// The generated wire contract exposes timestamps as strings; do not impose
// additional date parsing or timezone restrictions at this projection boundary.
const timestamp = z.string();
const bridgeIdentity = {
  bridge_identity: nonEmptyString,
  originating_run_id: nonEmptyString,
  client_tool_call_id: nonEmptyString,
  session_agent_context_id: nonEmptyString,
  originating_agent_session_id: nonEmptyString,
};

const actionSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("command"), name: nonEmptyString }),
  z.object({ type: z.literal("goal") }),
  z.object({ type: z.literal("skill"), skill_path: nonEmptyString }),
  z.object({
    type: z.literal("create_git_worktree"),
    source_project_path: nonEmptyString,
    starting_ref: nonEmptyString,
  }),
  z.object({ type: z.literal("cleanup_orphan_git_worktrees") }),
  z.object({ type: z.literal("create_session_working_folder") }),
  z.object({
    type: z.literal("agent_create_git_worktree"),
    ...bridgeIdentity,
    source_project_id: nonEmptyString,
    source_project_path: nonEmptyString,
    starting_ref: z.string().nullable(),
    branch_name: z.string().nullable(),
  }),
  z.object({
    type: z.literal("agent_remove_git_worktree"),
    ...bridgeIdentity,
    worktree_project_id: nonEmptyString,
    worktree_allocation_id: nonEmptyString,
    worktree_path: nonEmptyString,
    force: z.boolean(),
  }),
]);

// Public response objects may grow additive fields. Decode the declared shape
// without retaining unknown fields, while preserving omission and explicit null.
const projectionSchema = z.object({
  execution: z
    .object({
      id: z.string(),
      source_mailbox_item_id: z.string(),
      sender_user_id: z.string().nullable(),
      action_type: z.string(),
      action: actionSchema,
      result: z.record(z.string(), z.json()).nullable().optional(),
      status: z.string(),
      owner_generation: z.number().int(),
      failure_summary: z.string().nullable().optional(),
      cancellation_summary: z.string().nullable().optional(),
      started_at: timestamp.nullable().optional(),
      completed_at: timestamp.nullable().optional(),
      failed_at: timestamp.nullable().optional(),
      cancelled_at: timestamp.nullable().optional(),
      updated_at: timestamp,
    })
    .refine((execution) => execution.action_type === execution.action.type),
  events: z.array(
    z.object({
      id: z.string(),
      action_execution_id: z.string(),
      sequence: z.number().int(),
      kind: z.string(),
      step_key: z.string().nullable().optional(),
      command_argv: z.array(z.string()).nullable().optional(),
      content: z.string().nullable().optional(),
      exit_code: z.number().int().nullable().optional(),
      created_at: timestamp,
    }),
  ),
}) satisfies z.ZodType<ActionExecutionProjectionResponse>;

const liveEventSchema = z.object({
  type: z.literal("action_execution_updated"),
  session_id: z.string(),
  action_execution: projectionSchema,
});

export function decodeActionExecutionProjection(
  value: unknown,
): ActionExecutionProjectionResponse | null {
  const result = projectionSchema.safeParse(value);
  return result.success ? result.data : null;
}

export function actionExecutionResultFromEvent(
  event: ChatEventResponse,
): ActionExecutionProjection | null {
  if (event.kind !== "action_execution_result") {
    return null;
  }
  const result = z
    .object({ action_execution: projectionSchema })
    .safeParse(event.payload);
  if (!result.success) {
    return null;
  }
  return {
    ...result.data.action_execution,
    provenance: "durable",
    historyEventId: event.id,
    historyCreatedAt: event.created_at,
  };
}

export function actionExecutionUpdatedEventFromValue(
  value: unknown,
  sessionId: string,
): ActionExecutionUpdatedEvent | null {
  const result = liveEventSchema.safeParse(value);
  if (!result.success || result.data.session_id !== sessionId) {
    return null;
  }
  return {
    ...result.data,
    action_execution: { ...result.data.action_execution, provenance: "live" },
  };
}
