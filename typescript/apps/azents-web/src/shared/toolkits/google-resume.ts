import { z } from "zod/v4";
import { googleScopeSchema } from "./google-schemas.ts";

export const GOOGLE_RESUME_KEY = "azents.google.connection";
const resumeSchema = googleScopeSchema
  .extend({
    toolkitId: z.string().min(1).optional(),
    attemptId: z.string().min(1).max(64),
    expiresAt: z.string().datetime({ offset: true }),
    stateDigest: z.string().regex(/^[a-f0-9]{64}$/),
    phase: z.enum([
      "AUTHORIZING",
      "REVIEW",
      "VERIFYING",
      "FAILED",
      "PUBLISHING",
      "UNKNOWN",
    ]),
    returnPath: z.string().startsWith("/w/"),
  })
  .strict();
export type GoogleResume = z.infer<typeof resumeSchema>;
export function googleReturnPath(
  handle: string,
  agentId?: string,
  toolkitId?: string,
): string {
  if (agentId != null) {
    return `/w/${handle}/agents/${agentId}/settings/capabilities#agent-toolkits`;
  }
  return toolkitId == null
    ? `/w/${handle}/toolkits/new`
    : `/w/${handle}/toolkits/${toolkitId}/edit`;
}
export function decodeGoogleResume(value: unknown): GoogleResume | null {
  const parsed = resumeSchema.safeParse(value);
  if (!parsed.success) {
    return null;
  }
  const data = parsed.data;
  return data.returnPath ===
    googleReturnPath(data.handle, data.agentId, data.toolkitId)
    ? data
    : null;
}
export function deserializeGoogleResume(value?: string): GoogleResume | null {
  if (!value) {
    return null;
  }
  try {
    return decodeGoogleResume(JSON.parse(value));
  } catch {
    return null;
  }
}
export function googleResumeMatches(
  context: GoogleResume,
  handle: string,
  agentId?: string,
  toolkitId?: string,
): boolean {
  return (
    context.handle === handle &&
    context.agentId === agentId &&
    context.toolkitId === toolkitId
  );
}
/** Opaque correlation only; server-owned encrypted state remains authoritative. */
export async function googleStateDigest(state: string): Promise<string> {
  const hash = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(state),
  );
  return Array.from(new Uint8Array(hash), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
