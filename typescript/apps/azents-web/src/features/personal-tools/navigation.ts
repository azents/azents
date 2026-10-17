import { z } from "zod/v4";

const segment = z.string().regex(/^[A-Za-z0-9_-]+$/);
const originSchema = z
  .object({
    originHandle: segment,
    originAgentId: segment,
    originSession: segment.optional(),
  })
  .strict();
export interface PersonalToolsOrigin {
  handle: string;
  agentId: string;
  sessionId?: string;
}

/** Decode route identity only; the caller must authorize it before displaying a return. */
export function parsePersonalToolsOrigin(
  query: Readonly<Record<string, unknown>>,
): PersonalToolsOrigin | null {
  const parsed = originSchema.safeParse({
    originHandle: query.originHandle,
    originAgentId: query.originAgentId,
    originSession: query.originSession,
  });
  return parsed.success
    ? {
        handle: parsed.data.originHandle,
        agentId: parsed.data.originAgentId,
        ...(parsed.data.originSession != null && {
          sessionId: parsed.data.originSession,
        }),
      }
    : null;
}

export function agentPersonalToolsPath(origin: PersonalToolsOrigin): string {
  const path = `/w/${encodeURIComponent(origin.handle)}/agents/${encodeURIComponent(origin.agentId)}/personal-tools`;
  return origin.sessionId == null
    ? path
    : `${path}?${new URLSearchParams({ originSession: origin.sessionId }).toString()}`;
}

export function personalToolsSetupPath(origin: PersonalToolsOrigin): string {
  const query = new URLSearchParams({
    originHandle: origin.handle,
    originAgentId: origin.agentId,
    ...(origin.sessionId != null && { originSession: origin.sessionId }),
  });
  return `/w/${encodeURIComponent(origin.handle)}/personal-tools/new?${query.toString()}`;
}

export function parseOriginSession(value: unknown): string | null {
  const parsed = segment.safeParse(value);
  return parsed.success ? parsed.data : null;
}
