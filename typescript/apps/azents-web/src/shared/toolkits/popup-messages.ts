import { z } from "zod/v4";

// These consumed projections preserve the existing callbacks' extension contract.
const githubPopupSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("azents-github-app-installed") }),
  z.object({
    type: z.literal("azents-github-installations-code"),
    code: z.string(),
    state: z.string(),
  }),
]);
const oauthCallbackSchema = z.object({
  type: z.literal("azents-oauth-callback"),
});
export type GitHubPopupMessage = z.infer<typeof githubPopupSchema>;
export type OAuthCallbackMessage = z.infer<typeof oauthCallbackSchema>;

/** Decode only an exact, current, same-origin popup handoff. */
export function decodeGitHubPopupMessage(
  event: { data: unknown; origin: string; source: unknown },
  origin: string,
  popup: unknown,
  current: boolean,
): GitHubPopupMessage | null {
  if (
    !current ||
    popup == null ||
    event.source !== popup ||
    event.origin !== origin
  ) {
    return null;
  }
  const result = githubPopupSchema.safeParse(event.data);
  return result.success ? result.data : null;
}

/** The existing MCP callback invalidates authoritative state regardless of success. */
export function decodeOAuthCallbackMessage(
  event: { data: unknown; origin: string },
  origin: string,
): OAuthCallbackMessage | null {
  if (event.origin !== origin) {
    return null;
  }
  const result = oauthCallbackSchema.safeParse(event.data);
  return result.success ? result.data : null;
}
