import { z } from "zod/v4";

export type McpCallbackTarget =
  | { type: "personal"; handle: string; toolkitId: string }
  | {
      type: "workload";
      handle: string;
      toolkitId: string;
      agentId: string | null;
    };

const personal = z
  .object({
    personal_toolkit_config_id: z.string().min(1),
    handle: z.string().min(1),
  })
  .strict();
const workload = z
  .object({
    handle: z.string().min(1),
    toolkit_config_id: z.string().min(1),
    agent_id: z.string().min(1).optional(),
  })
  .strict();

/** Query fields choose a callback route, never the authenticated credential owner. */
export function decodeMcpCallbackTarget(
  params: Record<string, string | string[] | null>,
): McpCallbackTarget | null {
  const fields = Object.fromEntries(
    ["personal_toolkit_config_id", "handle", "toolkit_config_id", "agent_id"]
      .filter((key) => params[key] != null)
      .map((key) => [key, params[key]]),
  );
  const account = personal.safeParse(fields);
  if (account.success) {
    return {
      type: "personal",
      handle: account.data.handle,
      toolkitId: account.data.personal_toolkit_config_id,
    };
  }
  const existing = workload.safeParse(fields);
  return existing.success
    ? {
        type: "workload",
        handle: existing.data.handle,
        toolkitId: existing.data.toolkit_config_id,
        agentId: existing.data.agent_id ?? null,
      }
    : null;
}
export function mcpCallbackReturnPath(
  target: McpCallbackTarget,
): string | null {
  if (target.type === "personal") {
    return `/w/${encodeURIComponent(target.handle)}/personal-tools/${encodeURIComponent(target.toolkitId)}/edit`;
  }
  return target.agentId == null
    ? null
    : `/w/${encodeURIComponent(target.handle)}/agents/${encodeURIComponent(target.agentId)}/settings/capabilities#agent-toolkits`;
}
