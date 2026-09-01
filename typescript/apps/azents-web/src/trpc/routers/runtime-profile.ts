import {
  runtimeProfileV1CreateProfileRecreation,
  runtimeProfileV1CreateWorkspaceRuntimeProfile,
  runtimeProfileV1DeleteWorkspaceRuntimeProfile,
  runtimeProfileV1GetWorkspaceRuntimeProfile,
  runtimeProfileV1GetWorkspaceRuntimeProfileDefault,
  runtimeProfileV1GetWorkspaceRuntimeProfileRecreation,
  runtimeProfileV1ListSelectableInfrastructureProfiles,
  runtimeProfileV1ListWorkspaceRuntimeProfiles,
  runtimeProfileV1ReplaceWorkspaceRuntimeProfile,
  runtimeProfileV1ReplaceWorkspaceRuntimeProfileDefault,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const lifecycleSchema = z.enum(["active", "disabled"]);
const legacyNetworkPolicySchema = z
  .object({
    schemaVersion: z.literal(1),
    networkRestriction: z
      .object({
        allowedCidrs: z.array(z.string().min(1)),
        deniedCidrs: z.array(z.string().min(1)),
      })
      .nullable(),
  })
  .strict();
const proxyDomainPolicySchema = z.union([
  z
    .object({
      mode: z.literal("unrestricted"),
      allowedDomains: z.array(z.string().min(1)).length(0),
      deniedDomains: z.array(z.string().min(1)),
    })
    .strict(),
  z
    .object({
      mode: z.literal("allowlist"),
      allowedDomains: z.array(z.string().min(1)),
      deniedDomains: z.array(z.string().min(1)),
    })
    .strict(),
]);
const hierarchicalNetworkPolicySchema = z
  .object({
    schemaVersion: z.literal(2),
    networkRestriction: z.union([
      z.object({ mode: z.literal("inherit") }).strict(),
      z
        .object({
          mode: z.literal("direct"),
          allowedCidrs: z.array(z.string().min(1)),
          deniedCidrs: z.array(z.string().min(1)),
        })
        .strict(),
      z
        .object({
          mode: z.literal("proxy_required"),
          allowedCidrs: z.array(z.string().min(1)),
          deniedCidrs: z.array(z.string().min(1)),
          domainPolicy: proxyDomainPolicySchema,
        })
        .strict(),
      z.object({ mode: z.literal("no_network") }).strict(),
    ]),
  })
  .strict();
const workspacePolicySchema = z.union([
  legacyNetworkPolicySchema,
  hierarchicalNetworkPolicySchema,
]);

function workspacePolicyBody(policy: z.infer<typeof workspacePolicySchema>):
  | {
      schema_version: 1;
      network_restriction: {
        allowed_cidrs: string[];
        denied_cidrs: string[];
      } | null;
    }
  | {
      schema_version: 2;
      network_restriction:
        | { mode: "inherit" }
        | {
            mode: "direct";
            allowed_cidrs: string[];
            denied_cidrs: string[];
          }
        | {
            mode: "proxy_required";
            allowed_cidrs: string[];
            denied_cidrs: string[];
            domain_policy:
              | {
                  mode: "unrestricted";
                  allowed_domains: string[];
                  denied_domains: string[];
                }
              | {
                  mode: "allowlist";
                  allowed_domains: string[];
                  denied_domains: string[];
                };
          }
        | { mode: "no_network" };
    } {
  if (policy.schemaVersion === 1) {
    return {
      schema_version: 1,
      network_restriction:
        policy.networkRestriction === null
          ? null
          : {
              allowed_cidrs: policy.networkRestriction.allowedCidrs,
              denied_cidrs: policy.networkRestriction.deniedCidrs,
            },
    };
  }
  const restriction = policy.networkRestriction;
  if (restriction.mode === "inherit" || restriction.mode === "no_network") {
    return {
      schema_version: 2,
      network_restriction: { mode: restriction.mode },
    };
  }
  if (restriction.mode === "direct") {
    return {
      schema_version: 2,
      network_restriction: {
        mode: "direct",
        allowed_cidrs: restriction.allowedCidrs,
        denied_cidrs: restriction.deniedCidrs,
      },
    };
  }
  return {
    schema_version: 2,
    network_restriction: {
      mode: "proxy_required",
      allowed_cidrs: restriction.allowedCidrs,
      denied_cidrs: restriction.deniedCidrs,
      domain_policy: {
        mode: restriction.domainPolicy.mode,
        allowed_domains: restriction.domainPolicy.allowedDomains,
        denied_domains: restriction.domainPolicy.deniedDomains,
      },
    },
  };
}

export const runtimeProfileRouter = router({
  list: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        includeDisabled: z.boolean().optional(),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProfileV1ListWorkspaceRuntimeProfiles({
          client: ctx.apiClient,
          path: { handle: input.handle },
          query: { include_disabled: input.includeDisabled ?? false },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  listInfrastructureProfiles: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } =
          await runtimeProfileV1ListSelectableInfrastructureProfiles({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  getDefault: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } =
          await runtimeProfileV1GetWorkspaceRuntimeProfileDefault({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  create: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        infrastructureProfileId: z.string().min(1),
        displayName: z.string().min(1).max(120),
        description: z.string().max(1000),
        lifecycle: lifecycleSchema,
        policy: workspacePolicySchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProfileV1CreateWorkspaceRuntimeProfile({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            infrastructure_profile_id: input.infrastructureProfileId,
            display_name: input.displayName,
            description: input.description,
            lifecycle: input.lifecycle,
            policy: workspacePolicyBody(input.policy),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  replace: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        profileId: z.string().min(1),
        expectedVersion: z.number().int().positive(),
        infrastructureProfileId: z.string().min(1),
        displayName: z.string().min(1).max(120),
        description: z.string().max(1000),
        lifecycle: lifecycleSchema,
        policy: workspacePolicySchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data: current } =
          await runtimeProfileV1GetWorkspaceRuntimeProfile({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              profile_id: input.profileId,
            },
            throwOnError: true,
          });
        const { data } = await runtimeProfileV1ReplaceWorkspaceRuntimeProfile({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            profile_id: input.profileId,
          },
          body: {
            expected_version: input.expectedVersion,
            infrastructure_profile_id: input.infrastructureProfileId,
            display_name: input.displayName,
            description: input.description,
            lifecycle: input.lifecycle,
            terminal_enabled: current.terminal_enabled,
            policy: workspacePolicyBody(input.policy),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  delete: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        profileId: z.string().min(1),
        expectedVersion: z.number().int().positive(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProfileV1DeleteWorkspaceRuntimeProfile({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            profile_id: input.profileId,
          },
          body: {
            expected_version: input.expectedVersion,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  replaceDefault: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        expectedVersion: z.number().int().positive(),
        profileId: z.string().min(1).nullable(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } =
          await runtimeProfileV1ReplaceWorkspaceRuntimeProfileDefault({
            client: ctx.apiClient,
            path: { handle: input.handle },
            body: {
              expected_version: input.expectedVersion,
              runtime_profile_id: input.profileId,
            },
            throwOnError: true,
          });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  createRecreation: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        profileId: z.string().min(1),
        expectedVersion: z.number().int().positive(),
        concurrencyLimit: z.number().int().min(1).max(32).optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeProfileV1CreateProfileRecreation({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            profile_id: input.profileId,
          },
          body: {
            expected_version: input.expectedVersion,
            ...(input.concurrencyLimit
              ? { concurrency_limit: input.concurrencyLimit }
              : {}),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  getRecreation: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        operationId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } =
          await runtimeProfileV1GetWorkspaceRuntimeProfileRecreation({
            client: ctx.apiClient,
            path: {
              handle: input.handle,
              operation_id: input.operationId,
            },
            query: { offset: 0, limit: 100 },
            throwOnError: true,
          });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),
});
