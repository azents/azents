import {
  githubSetupV1AgentSetupApp,
  githubSetupV1AgentSetupVerification,
  githubSetupV1SharedSetupApp,
  githubSetupV1SharedSetupVerification,
  personalGithubToolkitV1PersonalGithubSetupApp,
  personalGithubToolkitV1PersonalGithubSetupVerify,
} from "@azents/public-client";
import { z } from "zod/v4";
import { toolkitScopedInput } from "@/shared/toolkits/toolkit-owner-scope";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const scope = toolkitScopedInput({});
const numericId = z.string().regex(/^[1-9][0-9]*$/);
const transport = z
  .object({ toolsets: z.array(z.string()), timeout: z.number().positive() })
  .strict();
const verification = z.discriminatedUnion("github_auth_type", [
  z
    .object({
      github_auth_type: z.literal("pat"),
      token: z.string().min(1),
      transport,
    })
    .strict(),
  z
    .object({
      github_auth_type: z.literal("github_app"),
      app_id: numericId,
      private_key: z.string().min(1),
      installation_ids: z.array(numericId).min(1),
      transport,
    })
    .strict(),
  z
    .object({
      github_auth_type: z.literal("github_app_platform"),
      installation_ids: z.array(numericId).min(1),
      transport,
    })
    .strict(),
]);
async function request<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch (error) {
    throw mapExpectedError(error, {
      400: "BAD_REQUEST",
      401: "UNAUTHORIZED",
      403: "FORBIDDEN",
      404: "NOT_FOUND",
      409: "CONFLICT",
      422: "BAD_REQUEST",
    });
  }
}
export const githubSetupRouter = router({
  app: publicProcedure.input(scope).query(async ({ ctx, input }) => {
    if ("owner" in input) {
      const { data } = await request(() =>
        personalGithubToolkitV1PersonalGithubSetupApp({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        }),
      );
      return data;
    }
    const { data } = await request(() =>
      input.agentId == null
        ? githubSetupV1SharedSetupApp({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          })
        : githubSetupV1AgentSetupApp({
            client: ctx.apiClient,
            path: { handle: input.handle, agent_id: input.agentId },
            throwOnError: true,
          }),
    );
    return data;
  }),
  verify: publicProcedure
    .input(toolkitScopedInput({ verification }))
    .mutation(async ({ ctx, input }) => {
      if ("owner" in input) {
        const { data } = await request(() =>
          personalGithubToolkitV1PersonalGithubSetupVerify({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body: input.verification,
            throwOnError: true,
          }),
        );
        return data;
      }
      const { data } = await request(() =>
        input.agentId == null
          ? githubSetupV1SharedSetupVerification({
              client: ctx.apiClient,
              path: { handle: input.handle },
              body: input.verification,
              throwOnError: true,
            })
          : githubSetupV1AgentSetupVerification({
              client: ctx.apiClient,
              path: { handle: input.handle, agent_id: input.agentId },
              body: input.verification,
              throwOnError: true,
            }),
      );
      return data;
    }),
});
