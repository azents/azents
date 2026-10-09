import { z } from "zod/v4";

export const GITHUB_USER_CREATION_KEY = "azents.github-user.creation";
const schema = z
  .object({
    handle: z.string().min(1),
    agentId: z.string().min(1).optional(),
    attemptId: z.string().regex(/^[a-zA-Z0-9_-]{1,64}$/),
    returnPath: z.string().startsWith("/w/"),
    phase: z.enum(["AUTHORIZING", "REVIEW", "ERROR"]),
  })
  .strict();
export type GitHubUserCreationContext = z.infer<typeof schema>;
export function creationReturnPath(handle: string, agentId?: string): string {
  return agentId == null
    ? `/w/${handle}/toolkits/new`
    : `/w/${handle}/agents/${agentId}/settings/capabilities#agent-toolkits`;
}
export function deserializeGitHubUserCreation(
  value?: string,
): GitHubUserCreationContext | null {
  if (!value) {
    return null;
  }
  try {
    const result = schema.safeParse(JSON.parse(value));
    if (
      !result.success ||
      result.data.returnPath !==
        creationReturnPath(result.data.handle, result.data.agentId)
    ) {
      return null;
    }
    return result.data;
  } catch {
    return null;
  }
}
export function parseGitHubCreationState(state: string | null): string | null {
  const parts = state?.split(".");
  return parts?.length === 3 &&
    parts[0] === "github_user_create" &&
    /^[a-zA-Z0-9_-]{1,64}$/.test(parts[1] ?? "") &&
    /^[a-zA-Z0-9_-]+$/.test(parts[2] ?? "")
    ? (parts[1] ?? null)
    : null;
}
