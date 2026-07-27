import {
  agentRuntimeV1GetAgentRuntime,
  runtimeExecutionV1ApplyAgentPolicy,
  runtimeExecutionV1GetAgentPolicy,
  runtimeExecutionV1GetWorkspacePolicy,
  runtimeExecutionV1ListAgentAuditEvents,
  runtimeExecutionV1ListWorkspaceAuditEvents,
  runtimeExecutionV1ListWorkspaceProfiles,
  runtimeExecutionV1ReplaceAgentPolicy,
  runtimeExecutionV1ReplaceWorkspacePolicy,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const resourceRestrictionSchema = z.object({
  cpu_millicores: z.number().int().nonnegative().nullable(),
  memory_bytes: z.number().int().nonnegative().nullable(),
  pids: z.number().int().nonnegative().nullable(),
  container_count: z.number().int().nonnegative().nullable(),
  ephemeral_storage_bytes: z.number().int().nonnegative().nullable(),
});

const restrictionSchema = z.object({
  schema_version: z.literal(1),
  image_build: z.object({ enabled: z.literal(false) }).nullable(),
  container_run: z.object({ enabled: z.literal(false) }).nullable(),
  compose: z.object({ enabled: z.literal(false) }).nullable(),
  resources: resourceRestrictionSchema.nullable(),
  engine_storage: z
    .object({
      mode: z.enum(["none", "ephemeral", "persistent"]).nullable(),
      capacity_bytes: z.number().int().nonnegative().nullable(),
    })
    .nullable(),
  network_egress: z
    .object({
      mode: z.enum(["none", "restricted", "direct"]).nullable(),
      allowed_destinations: z.array(z.string()).nullable(),
      denied_destinations: z.array(z.string()),
    })
    .nullable(),
});

const workspaceInput = z.object({ handle: z.string().min(1) });
const agentInput = z.object({
  handle: z.string().min(1),
  agentId: z.string().min(1),
});

export const runtimeExecutionRouter = router({
  getWorkspacePolicy: publicProcedure
    .input(workspaceInput)
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1GetWorkspacePolicy({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  listWorkspaceProfiles: publicProcedure
    .input(workspaceInput)
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1ListWorkspaceProfiles({
          client: ctx.apiClient,
          path: { handle: input.handle },
          query: { include_retired: true, offset: 0, limit: 100 },
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

  listWorkspaceAuditEvents: publicProcedure
    .input(workspaceInput)
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1ListWorkspaceAuditEvents({
          client: ctx.apiClient,
          path: { handle: input.handle },
          query: { offset: 0, limit: 100 },
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

  replaceWorkspacePolicy: publicProcedure
    .input(
      workspaceInput.extend({
        expectedVersion: z.number().int().nonnegative(),
        restriction: restrictionSchema,
        allowedProfileIds: z.array(z.string().min(1)).min(1).max(100),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1ReplaceWorkspacePolicy({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            expected_version: input.expectedVersion,
            restriction: input.restriction,
            allowed_profile_ids: input.allowedProfileIds,
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

  getAgentPolicy: publicProcedure
    .input(agentInput)
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1GetAgentPolicy({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  getAgentStatus: publicProcedure
    .input(agentInput)
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await agentRuntimeV1GetAgentRuntime({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          throwOnError: true,
        });
        return data.execution_policy;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),

  listAgentAuditEvents: publicProcedure
    .input(agentInput)
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1ListAgentAuditEvents({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
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

  replaceAgentPolicy: publicProcedure
    .input(
      agentInput.extend({
        expectedVersion: z.number().int().positive(),
        profileId: z.string().min(1).max(32),
        restriction: restrictionSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1ReplaceAgentPolicy({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: {
            expected_version: input.expectedVersion,
            profile_id: input.profileId,
            restriction: input.restriction,
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

  applyAgentPolicy: publicProcedure
    .input(agentInput)
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeExecutionV1ApplyAgentPolicy({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),
});
