import { isRoutineToolCall } from "@azents/session-core/routinePresentation";
import { z } from "zod";
import type { KnownToolPresentationResult } from "./knownToolPresentation.ts";
import type { RoutineToolName } from "@azents/session-core/routinePresentation";
import type { ActiveToolCall } from "@azents/session-core/types";

const nonblank = z.string().refine((value) => value.trim().length > 0);
const timestamp = z.string().datetime({ offset: true });
const sourceSchema = z.object({ type: z.literal("manual") }).strict();
export const routineContentSchema = z
  .object({
    title: nonblank,
    objective: nonblank,
    sources: z.array(sourceSchema),
  })
  .strict();
const changesSchema = routineContentSchema.partial();
const scopeSchema = z
  .object({ workspace_id: nonblank, agent_id: nonblank, session_id: nonblank })
  .strict();
export const routineWorkSchema = z
  .object({
    objective_outcome: z.enum(["finished", "failed"]),
    result: nonblank,
    next_hint: nonblank,
    notify: z.boolean(),
    message: z.string().nullable(),
  })
  .strict()
  .refine((value) =>
    value.notify
      ? value.message !== null && value.message.trim().length > 0
      : value.message === null,
  );
const deliverySchema = z.enum([
  "not_requested",
  "unobserved",
  "delivered",
  "failed",
]);
const definitionSchema = z
  .object({
    id: nonblank,
    scope: scopeSchema,
    slug: nonblank,
    content: routineContentSchema,
    created_at: timestamp,
    updated_at: timestamp,
  })
  .strict();
const recordSchema = z
  .object({
    id: nonblank,
    routine_id: nonblank,
    execution_id: nonblank,
    started_at: timestamp,
    completed_at: timestamp,
    work: routineWorkSchema,
    delivery_status: deliverySchema,
    delivery_error: z.string().nullable(),
  })
  .strict();
const candidateSchema = z
  .object({
    routine_id: nonblank,
    slug: nonblank,
    content: routineContentSchema,
    events: z
      .array(
        z
          .object({ source_type: z.literal("manual"), observed_at: timestamp })
          .strict(),
      )
      .min(1),
    last_executed_at: timestamp.nullable(),
    latest_work: routineWorkSchema.nullable(),
  })
  .strict();
const contextSchema = z
  .object({
    execution_id: nonblank,
    judgment_id: nonblank,
    scope: scopeSchema,
    candidate: candidateSchema,
    admitted_at: timestamp,
  })
  .strict();
const completionSchema = z
  .object({
    context: contextSchema,
    phase: z.literal("completed"),
    current_run_id: nonblank,
    started_at: timestamp,
    completed_at: timestamp,
    work: routineWorkSchema,
    delivery_status: deliverySchema,
    delivery_error: z.string().nullable(),
  })
  .strict()
  .refine((value) =>
    value.work.notify
      ? value.delivery_status !== "not_requested"
      : value.delivery_status === "not_requested",
  )
  .refine(
    (value) =>
      value.delivery_error === null || value.delivery_status === "failed",
  );
const identitySchema = z.object({ slug: nonblank }).strict();
const inspectSchema = identitySchema.extend({
  record_limit: z.number().int().min(1).max(100),
});
const updateSchema = identitySchema.extend({
  expected: routineContentSchema,
  changes: changesSchema,
});
const executionInputSchema = identitySchema.extend({ execution_id: nonblank });
const recordInputSchema = executionInputSchema.extend({
  work: routineWorkSchema,
});

export type RoutineToolAction =
  | "createRoutine"
  | "listRoutines"
  | "inspectRoutine"
  | "updateRoutine"
  | "deleteRoutine"
  | "readRoutineContext"
  | "recordRoutineResult";
export type RoutineContentView = z.infer<typeof routineContentSchema>;
export type RoutineWorkView = z.infer<typeof routineWorkSchema>;
export type RoutineToolRequest =
  | { type: "createRoutine"; content: RoutineContentView }
  | { type: "listRoutines" }
  | { type: "inspectRoutine"; slug: string; recordLimit: number }
  | {
      type: "updateRoutine";
      slug: string;
      expected: RoutineContentView;
      changes: z.infer<typeof changesSchema>;
    }
  | { type: "deleteRoutine"; slug: string }
  | { type: "readRoutineContext"; slug: string; executionId: string }
  | {
      type: "recordRoutineResult";
      slug: string;
      executionId: string;
      work: RoutineWorkView;
    };
export type RoutineToolResult =
  | { type: "definition"; definition: z.infer<typeof definitionSchema> }
  | { type: "inventory"; items: z.infer<typeof definitionSchema>[] }
  | {
      type: "inspection";
      detail: {
        definition: z.infer<typeof definitionSchema>;
        records: z.infer<typeof recordSchema>[];
      } | null;
    }
  | { type: "context"; context: z.infer<typeof contextSchema> }
  | {
      type: "completion";
      created: boolean;
      execution: z.infer<typeof completionSchema>;
    };
export interface RoutineToolDetail {
  type: "routine";
  request: RoutineToolRequest | null;
  outcome:
    | { type: "PENDING" }
    | { type: "UNSUCCEEDED"; status: "failed" | "cancelled" | "interrupted" }
    | { type: "COMPLETED"; result: RoutineToolResult };
}

function json(value: string): unknown {
  try {
    const decoded: unknown = JSON.parse(value);
    return decoded;
  } catch (error) {
    if (error instanceof SyntaxError) {
      return null;
    }
    throw error;
  }
}

function requestFor(
  name: RoutineToolName,
  value: unknown,
): RoutineToolRequest | null {
  switch (name) {
    case "create_routine": {
      const input = routineContentSchema.safeParse(value);
      return input.success
        ? { type: "createRoutine", content: input.data }
        : null;
    }
    case "list_routines":
      return z.object({}).strict().safeParse(value).success
        ? { type: "listRoutines" }
        : null;
    case "inspect_routine": {
      const input = inspectSchema.safeParse(value);
      return input.success
        ? {
            type: "inspectRoutine",
            slug: input.data.slug,
            recordLimit: input.data.record_limit,
          }
        : null;
    }
    case "update_routine": {
      const input = updateSchema.safeParse(value);
      return input.success
        ? {
            type: "updateRoutine",
            slug: input.data.slug,
            expected: input.data.expected,
            changes: input.data.changes,
          }
        : null;
    }
    case "delete_routine": {
      const input = identitySchema.safeParse(value);
      return input.success
        ? { type: "deleteRoutine", slug: input.data.slug }
        : null;
    }
    case "read_routine_context": {
      const input = executionInputSchema.safeParse(value);
      return input.success
        ? {
            type: "readRoutineContext",
            slug: input.data.slug,
            executionId: input.data.execution_id,
          }
        : null;
    }
    case "record_routine_result": {
      const input = recordInputSchema.safeParse(value);
      return input.success
        ? {
            type: "recordRoutineResult",
            slug: input.data.slug,
            executionId: input.data.execution_id,
            work: input.data.work,
          }
        : null;
    }
  }
}

function sameContent(
  first: RoutineContentView,
  second: RoutineContentView,
): boolean {
  return (
    first.title === second.title &&
    first.objective === second.objective &&
    JSON.stringify(first.sources) === JSON.stringify(second.sources)
  );
}

function resultFor(
  request: RoutineToolRequest,
  value: unknown,
): RoutineToolResult | null {
  switch (request.type) {
    case "createRoutine":
    case "updateRoutine": {
      const result = definitionSchema.safeParse(value);
      if (!result.success) {
        return null;
      }
      const intended =
        request.type === "createRoutine"
          ? request.content
          : { ...request.expected, ...request.changes };
      if (
        !sameContent(result.data.content, intended) ||
        (request.type === "updateRoutine" && result.data.slug !== request.slug)
      ) {
        return null;
      }
      return { type: "definition", definition: result.data };
    }
    case "listRoutines": {
      const result = z
        .object({ routines: z.array(definitionSchema).max(20) })
        .strict()
        .safeParse(value);
      return result.success
        ? { type: "inventory", items: result.data.routines }
        : null;
    }
    case "inspectRoutine": {
      const result = z
        .object({
          routine: z
            .object({
              definition: definitionSchema,
              records: z.array(recordSchema).max(100),
            })
            .strict()
            .nullable(),
        })
        .strict()
        .safeParse(value);
      if (!result.success) {
        return null;
      }
      const detail = result.data.routine;
      if (
        detail !== null &&
        (detail.definition.slug !== request.slug ||
          detail.records.length > request.recordLimit ||
          detail.records.some(
            (record) => record.routine_id !== detail.definition.id,
          ))
      ) {
        return null;
      }
      return { type: "inspection", detail };
    }
    case "deleteRoutine": {
      const result = z
        .object({ deleted: z.literal(true), routine: definitionSchema })
        .strict()
        .safeParse(value);
      return result.success && result.data.routine.slug === request.slug
        ? { type: "definition", definition: result.data.routine }
        : null;
    }
    case "readRoutineContext": {
      const result = contextSchema.safeParse(value);
      return result.success &&
        result.data.execution_id === request.executionId &&
        result.data.candidate.slug === request.slug
        ? { type: "context", context: result.data }
        : null;
    }
    case "recordRoutineResult": {
      const result = z
        .object({ created: z.boolean(), execution: completionSchema })
        .strict()
        .safeParse(value);
      if (
        !result.success ||
        result.data.execution.context.execution_id !== request.executionId ||
        result.data.execution.context.candidate.slug !== request.slug
      ) {
        return null;
      }
      if (
        result.data.created &&
        JSON.stringify(result.data.execution.work) !==
          JSON.stringify(request.work)
      ) {
        return null;
      }
      return { type: "completion", ...result.data };
    }
  }
}

function actionFor(name: RoutineToolName): RoutineToolAction {
  switch (name) {
    case "create_routine":
      return "createRoutine";
    case "list_routines":
      return "listRoutines";
    case "inspect_routine":
      return "inspectRoutine";
    case "update_routine":
      return "updateRoutine";
    case "delete_routine":
      return "deleteRoutine";
    case "read_routine_context":
      return "readRoutineContext";
    case "record_routine_result":
      return "recordRoutineResult";
  }
}

function subject(
  request: RoutineToolRequest | null,
  result: RoutineToolResult | null,
): string | null {
  if (result?.type === "definition") {
    return result.definition.content.title;
  }
  if (result?.type === "inspection") {
    return (
      result.detail?.definition.content.title ??
      (request !== null && "slug" in request ? request.slug : null)
    );
  }
  if (result?.type === "context") {
    return result.context.candidate.content.title;
  }
  if (result?.type === "completion") {
    return result.execution.context.candidate.content.title;
  }
  if (request === null || request.type === "listRoutines") {
    return null;
  }
  if (request.type === "createRoutine") {
    return request.content.title;
  }
  if (request.type === "updateRoutine") {
    return request.expected.title;
  }
  return request.slug;
}

export function routineToolPresentation(
  call: ActiveToolCall,
): KnownToolPresentationResult | null {
  if (!isRoutineToolCall(call)) {
    return null;
  }
  if (call.wireDialect === "plaintext_custom") {
    return { type: "generic", reason: "invalid-arguments" };
  }
  const request = requestFor(call.name, json(call.arguments));
  if (request === null && call.status !== "preparing") {
    return { type: "generic", reason: "invalid-arguments" };
  }
  let outcome: RoutineToolDetail["outcome"];
  if (call.status === "preparing" || call.status === "running") {
    outcome = { type: "PENDING" };
  } else if (call.status === "completed") {
    if (request === null || typeof call.result !== "string") {
      return { type: "generic", reason: "invalid-output" };
    }
    const result = resultFor(request, json(call.result));
    if (result === null) {
      return { type: "generic", reason: "invalid-output" };
    }
    outcome = { type: "COMPLETED", result };
  } else {
    outcome = { type: "UNSUCCEEDED", status: call.status };
  }
  const result = outcome.type === "COMPLETED" ? outcome.result : null;
  return {
    type: "specialized",
    presentation: {
      action: actionFor(call.name),
      subject: subject(request, result),
      qualifier:
        result?.type === "inventory" ? String(result.items.length) : null,
      detail: { type: "routine", request, outcome },
    },
  };
}
