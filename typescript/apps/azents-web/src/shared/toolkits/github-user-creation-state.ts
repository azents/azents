import { z } from "zod/v4";
import {
  isToolkitManagementPath,
  pickToolkitOwnerScope,
  sameToolkitOwnerScope,
  toolkitManagementPath,
  toolkitScopedInput,
} from "./toolkit-owner-scope.ts";
import type {
  PersonalToolkitOrigin,
  ToolkitOwnerScope,
} from "./toolkit-owner-scope.ts";

export const GITHUB_USER_CREATION_KEY = "azents.github-user.creation";
const schema = toolkitScopedInput({
  attemptId: z.string().regex(/^[a-zA-Z0-9_-]{1,64}$/),
  returnPath: z.string().startsWith("/"),
  phase: z.enum(["AUTHORIZING", "REVIEW", "ERROR"]),
});
export type GitHubUserCreationContext = z.infer<typeof schema>;
export function creationReturnPath(
  scope: ToolkitOwnerScope,
  origin?: PersonalToolkitOrigin,
): string {
  return toolkitManagementPath(scope, null, origin);
}
export function gitHubCreationScope(
  context: GitHubUserCreationContext,
): ToolkitOwnerScope {
  return pickToolkitOwnerScope(context);
}
export function gitHubCreationMatches(
  context: GitHubUserCreationContext,
  scope: ToolkitOwnerScope,
): boolean {
  return (
    sameToolkitOwnerScope(context, scope) &&
    isToolkitManagementPath(scope, null, context.returnPath)
  );
}
export function deserializeGitHubUserCreation(
  value?: string,
): GitHubUserCreationContext | null {
  if (!value) {
    return null;
  }
  try {
    const result = schema.safeParse(JSON.parse(value));
    return result.success && gitHubCreationMatches(result.data, result.data)
      ? result.data
      : null;
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
