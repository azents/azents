import { z } from "zod/v4";
import {
  isToolkitManagementPath,
  sameToolkitOwnerScope,
  toolkitManagementPath,
  toolkitScopedInput,
} from "./toolkit-owner-scope.ts";
import type {
  PersonalToolkitOrigin,
  ToolkitOwnerScope,
} from "./toolkit-owner-scope.ts";

export const GOOGLE_RESUME_KEY = "azents.google.connection";
const resumeSchema = toolkitScopedInput({
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
  returnPath: z.string().startsWith("/"),
  purpose: z.enum(["CONNECT", "RECOVER", "APPLY"]).optional(),
  returnAgentId: z
    .string()
    .regex(/^[A-Za-z0-9_-]+$/)
    .optional(),
});
export type GoogleResume = z.infer<typeof resumeSchema>;

export function googleResumeScope(context: GoogleResume): ToolkitOwnerScope {
  return "owner" in context
    ? { owner: context.owner, handle: context.handle }
    : { handle: context.handle, agentId: context.agentId };
}
export function googleReturnPath(
  scope: ToolkitOwnerScope,
  toolkitId?: string,
  origin?: PersonalToolkitOrigin,
): string {
  return toolkitManagementPath(scope, toolkitId ?? null, origin);
}
export function decodeGoogleResume(value: unknown): GoogleResume | null {
  const parsed = resumeSchema.safeParse(value);
  if (!parsed.success) {
    return null;
  }
  const data = parsed.data;
  const agentReturn =
    !("owner" in data) &&
    data.returnAgentId != null &&
    data.returnPath === googleAgentReturnPath(data.handle, data.returnAgentId);
  return agentReturn ||
    isToolkitManagementPath(
      googleResumeScope(data),
      data.toolkitId ?? null,
      data.returnPath,
    )
    ? data
    : null;
}
export function googleAgentReturnPath(handle: string, agentId: string): string {
  return `/w/${encodeURIComponent(handle)}/agents/${encodeURIComponent(agentId)}/settings/capabilities#agent-toolkits`;
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
  scope: ToolkitOwnerScope,
  toolkitId?: string,
): boolean {
  return (
    sameToolkitOwnerScope(googleResumeScope(context), scope) &&
    context.toolkitId === toolkitId
  );
}
export function sameGoogleResumeAttempt(
  current: GoogleResume | null,
  expected: GoogleResume,
): boolean {
  return (
    current != null &&
    googleResumeMatches(
      current,
      googleResumeScope(expected),
      expected.toolkitId,
    ) &&
    current.attemptId === expected.attemptId &&
    current.stateDigest === expected.stateDigest &&
    current.expiresAt === expected.expiresAt &&
    current.returnPath === expected.returnPath &&
    current.purpose === expected.purpose &&
    current.returnAgentId === expected.returnAgentId
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
