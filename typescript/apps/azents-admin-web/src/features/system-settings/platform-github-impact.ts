import { z } from "zod/v4";

const displayedCountSchema = z
  .custom<number>((value) => typeof value === "number")
  .nullable()
  .catch(null)
  .default(null);

const candidateImpactSchema = z.object({
  affected_user_count: displayedCountSchema,
  affected_installation_count: displayedCountSchema,
  affected_toolkit_count: displayedCountSchema,
  affected_agent_count: displayedCountSchema,
  confirmation_actions: z
    .preprocess(
      (value) =>
        Array.isArray(value)
          ? value.filter((item): item is string => typeof item === "string")
          : [],
      z.array(z.string()),
    )
    .default([]),
});

export type PlatformGitHubCandidateImpact = z.infer<
  typeof candidateImpactSchema
>;

/** Project interpreted fields while leaving the original extensible API impact opaque. */
export function projectPlatformGitHubCandidateImpact(
  impact: unknown,
): PlatformGitHubCandidateImpact {
  return candidateImpactSchema.parse(impact ?? {});
}
