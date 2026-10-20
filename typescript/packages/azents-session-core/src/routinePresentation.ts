import type { ActiveToolCall, ChatMessage } from "./types.ts";
import type { ChatEventResponse } from "@azents/public-client/types";

export type RoutineToolName =
  | "create_routine"
  | "list_routines"
  | "inspect_routine"
  | "update_routine"
  | "delete_routine"
  | "read_routine_context"
  | "record_routine_result";

export function isRoutineToolName(name: string): name is RoutineToolName {
  switch (name) {
    case "create_routine":
    case "list_routines":
    case "inspect_routine":
    case "update_routine":
    case "delete_routine":
    case "read_routine_context":
    case "record_routine_result":
      return true;
    default:
      return false;
  }
}

export function isRoutineToolCall(
  call: ActiveToolCall,
): call is ActiveToolCall & { name: RoutineToolName } {
  if (!isRoutineToolName(call.name)) {
    return false;
  }
  const source = call.toolkitSource;
  // Auto-bound builtins have no DB-attached Toolkit source snapshot.
  return source == null;
}

export interface RoutineCallUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  cachedTokens: number | null;
  cacheCreationTokens: number | null;
  reasoningTokens: number | null;
  costUsd: number | null;
}

export interface RoutineJudgmentItem {
  routineId: string;
  slug: string;
  title: string;
  act: boolean | null;
}

export type RoutineJudgmentView =
  | { type: "UNAVAILABLE" }
  | {
      type: "AVAILABLE";
      judgmentId: string;
      status: "completed" | "failed" | "cancelled";
      items: RoutineJudgmentItem[];
      error: string | null;
      callUsage: RoutineCallUsage | null;
    };

export interface RoutineInputContext {
  content: string;
  executions: {
    routineId: string;
    executionId: string;
    slug: string;
    title: string;
  }[];
}

export interface RoutineJudgmentMessage {
  observation: RoutineJudgmentView;
  provider: string | null;
  model: string | null;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function onlyKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function token(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function nullableToken(value: unknown): value is number | null {
  return value === null || token(value);
}

function callUsage(value: unknown): RoutineCallUsage | null {
  if (
    !record(value) ||
    !onlyKeys(value, [
      "prompt_tokens",
      "completion_tokens",
      "total_tokens",
      "cached_tokens",
      "cache_creation_tokens",
      "reasoning_tokens",
      "cost_usd",
      "cost_provenance",
    ])
  ) {
    return null;
  }
  if (
    !token(value.prompt_tokens) ||
    !token(value.completion_tokens) ||
    !token(value.total_tokens)
  ) {
    return null;
  }
  const cached = value.cached_tokens ?? null;
  const creation = value.cache_creation_tokens ?? null;
  const reasoning = value.reasoning_tokens ?? null;
  const cost = value.cost_usd ?? null;
  const provenance = value.cost_provenance ?? null;
  if (provenance !== null && !record(provenance)) {
    return null;
  }
  if (
    !nullableToken(cached) ||
    !nullableToken(creation) ||
    !nullableToken(reasoning)
  ) {
    return null;
  }
  if (
    cost !== null &&
    !(typeof cost === "number" && Number.isFinite(cost) && cost >= 0)
  ) {
    return null;
  }
  return {
    promptTokens: value.prompt_tokens,
    completionTokens: value.completion_tokens,
    totalTokens: value.total_tokens,
    cachedTokens: cached,
    cacheCreationTokens: creation,
    reasoningTokens: reasoning,
    costUsd: cost,
  };
}

export function decodeRoutineJudgment(value: unknown): RoutineJudgmentView {
  if (
    !record(value) ||
    !onlyKeys(value, [
      "judgment_id",
      "considered",
      "status",
      "decision",
      "error",
      "usage",
    ]) ||
    !text(value.judgment_id) ||
    !Array.isArray(value.considered) ||
    value.considered.length === 0
  ) {
    return { type: "UNAVAILABLE" };
  }
  const items: RoutineJudgmentItem[] = [];
  for (const item of value.considered) {
    if (
      !record(item) ||
      !onlyKeys(item, ["routine_id", "slug", "title"]) ||
      !text(item.routine_id) ||
      !text(item.slug) ||
      !text(item.title) ||
      items.some((other) => other.routineId === item.routine_id)
    ) {
      return { type: "UNAVAILABLE" };
    }
    items.push({
      routineId: item.routine_id,
      slug: item.slug,
      title: item.title,
      act: null,
    });
  }
  const usage = value.usage === null ? null : callUsage(value.usage);
  if (value.usage !== null && usage === null) {
    return { type: "UNAVAILABLE" };
  }
  if (value.status === "completed") {
    if (
      value.error !== null ||
      !record(value.decision) ||
      !onlyKeys(value.decision, ["decisions"]) ||
      !Array.isArray(value.decision.decisions) ||
      value.decision.decisions.length !== items.length
    ) {
      return { type: "UNAVAILABLE" };
    }
    const seen = new Set<string>();
    for (const decision of value.decision.decisions) {
      if (
        !record(decision) ||
        !onlyKeys(decision, ["routine_id", "act"]) ||
        !text(decision.routine_id) ||
        typeof decision.act !== "boolean" ||
        seen.has(decision.routine_id)
      ) {
        return { type: "UNAVAILABLE" };
      }
      const item = items.find(
        (candidate) => candidate.routineId === decision.routine_id,
      );
      if (!item) {
        return { type: "UNAVAILABLE" };
      }
      item.act = decision.act;
      seen.add(decision.routine_id);
    }
    return {
      type: "AVAILABLE",
      judgmentId: value.judgment_id,
      status: "completed",
      items,
      error: null,
      callUsage: usage,
    };
  }
  if (
    (value.status === "failed" || value.status === "cancelled") &&
    value.decision === null &&
    text(value.error)
  ) {
    return {
      type: "AVAILABLE",
      judgmentId: value.judgment_id,
      status: value.status,
      items,
      error: value.error,
      callUsage: usage,
    };
  }
  return { type: "UNAVAILABLE" };
}

export function decodeRoutineInput(value: unknown): RoutineInputContext | null {
  if (
    !record(value) ||
    !onlyKeys(value, ["executions", "content"]) ||
    !text(value.content) ||
    !Array.isArray(value.executions) ||
    value.executions.length === 0
  ) {
    return null;
  }
  const executions: RoutineInputContext["executions"] = [];
  for (const item of value.executions) {
    if (
      !record(item) ||
      !onlyKeys(item, ["routine_id", "execution_id", "slug", "title"]) ||
      !text(item.routine_id) ||
      !text(item.execution_id) ||
      !text(item.slug) ||
      !text(item.title) ||
      executions.some(
        (other) =>
          other.routineId === item.routine_id ||
          other.executionId === item.execution_id,
      )
    ) {
      return null;
    }
    executions.push({
      routineId: item.routine_id,
      executionId: item.execution_id,
      slug: item.slug,
      title: item.title,
    });
  }
  return { content: value.content, executions };
}

export function routineEventMessage(
  event: ChatEventResponse,
): ChatMessage | null {
  const identity = {
    id: event.id,
    createdAt: event.created_at,
    metadata: {
      event_id: event.id,
      event_render_key: `event:${event.external_id ?? event.id}`,
    },
  };
  switch (event.kind) {
    case "routine_judgment":
      return {
        ...identity,
        role: "routine_judgment",
        content: null,
        status: "complete",
        routineJudgment: {
          observation: decodeRoutineJudgment(event.payload),
          provider: event.provider ?? null,
          model: event.model ?? null,
        },
      };
    case "routine_trigger":
    case "routine_continuation": {
      const input = decodeRoutineInput(event.payload);
      return {
        ...identity,
        role: event.kind,
        content: input?.content ?? null,
        status: "complete",
        routineInput: input,
      };
    }
    case "routine_notification": {
      const payload = event.payload;
      if (
        !onlyKeys(payload, [
          "execution_id",
          "slug",
          "title",
          "content",
          "attachments",
        ]) ||
        !text(payload.execution_id) ||
        !text(payload.slug) ||
        !text(payload.title) ||
        !text(payload.content)
      ) {
        return null;
      }
      return {
        ...identity,
        role: "assistant",
        content: payload.content,
        status: "complete",
      };
    }
    default:
      return null;
  }
}
