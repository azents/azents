import { z } from "zod/v4";
import { browserToolTarget } from "../../shared/session-browser/route.ts";
import type { BrowserTarget } from "./types";
import type { ChatEventResponse } from "@azents/public-client";

const callSchema = z.object({ call_id: z.string(), name: z.string() });
const resultSchema = z.object({
  call_id: z.string(),
  name: z.string().nullish(),
  status: z.literal("completed"),
  output: z.union([
    z.string(),
    z.array(
      z.union([
        z.object({
          type: z.enum(["text", "output_text", "input_text"]),
          text: z.string(),
        }),
        z.object({ type: z.string() }),
      ]),
    ),
  ]),
});

/** A bounded authorized event snapshot supplies preference only, never live target authority. */
export function recentBrowserTargets(
  events: readonly Pick<
    ChatEventResponse,
    "id" | "kind" | "payload" | "created_at"
  >[],
): BrowserTarget[] {
  const names = new Map<string, string>();
  for (const event of events) {
    if (event.kind !== "client_tool_call") {
      continue;
    }
    const call = callSchema.safeParse(event.payload);
    if (call.success) {
      names.set(call.data.call_id, call.data.name);
    }
  }
  const result: BrowserTarget[] = [];
  const seen = new Set<string>();
  const ordered = [...events].sort(
    (a, b) =>
      b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id),
  );
  for (const event of ordered) {
    if (event.kind !== "client_tool_result") {
      continue;
    }
    const decoded = resultSchema.safeParse(event.payload);
    if (!decoded.success) {
      continue;
    }
    const payload = decoded.data;
    const name = payload.name ?? names.get(payload.call_id) ?? null;
    if (name === null) {
      continue;
    }
    const output =
      typeof payload.output === "string"
        ? payload.output
        : payload.output
            .flatMap((part) => ("text" in part ? [part.text] : []))
            .join("");
    const target = browserToolTarget(name, output);
    if (target === null) {
      continue;
    }
    const key = JSON.stringify(target);
    if (!seen.has(key)) {
      seen.add(key);
      result.push(target);
    }
  }
  return result;
}
