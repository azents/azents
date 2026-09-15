import {
  runtimeWebV1CreateRuntimeWebService,
  runtimeWebV1DeleteRuntimeWebService,
  runtimeWebV1GetRuntimeWebServiceById,
  runtimeWebV1GetRuntimeWebServiceProjection,
  runtimeWebV1ListRuntimeWebServices,
  runtimeWebV1ResetRuntimeWebServiceExpiration,
  runtimeWebV1TurnOffRuntimeWebService,
  runtimeWebV1TurnOnRuntimeWebService,
  runtimeWebV1TurnOnRuntimeWebServiceById,
  runtimeWebV1UpdateRuntimeWebService,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const durationSchema = z.union([
  z.literal(3600),
  z.literal(21_600),
  z.literal(86_400),
]);
const agentSchema = z.object({
  handle: z.string().min(1),
  agentId: z.string().min(1),
});
const serviceSchema = agentSchema.extend({
  serviceId: z.string().length(32),
});
const operationSchema = z.object({
  operationKey: z.string().min(1).max(128),
});
const revisionSchema = operationSchema.extend({
  expectedRevision: z.number().int().min(0),
});

const expectedErrors = {
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  409: "CONFLICT",
  429: "TOO_MANY_REQUESTS",
} as const;

export const runtimeWebRouter = router({
  list: publicProcedure.input(agentSchema).query(async ({ ctx, input }) => {
    try {
      const { data } = await runtimeWebV1ListRuntimeWebServices({
        client: ctx.apiClient,
        path: { handle: input.handle, agent_id: input.agentId },
        throwOnError: true,
      });
      return data;
    } catch (error) {
      throw mapExpectedError(error, expectedErrors);
    }
  }),

  get: publicProcedure.input(serviceSchema).query(async ({ ctx, input }) => {
    try {
      const { data } = await runtimeWebV1GetRuntimeWebServiceProjection({
        client: ctx.apiClient,
        path: {
          handle: input.handle,
          agent_id: input.agentId,
          service_id: input.serviceId,
        },
        throwOnError: true,
      });
      return data;
    } catch (error) {
      throw mapExpectedError(error, expectedErrors);
    }
  }),

  getById: publicProcedure
    .input(z.object({ serviceId: z.string().length(32) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1GetRuntimeWebServiceById({
          client: ctx.apiClient,
          path: { service_id: input.serviceId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  create: publicProcedure
    .input(
      agentSchema.merge(operationSchema).extend({
        port: z.number().int().min(1).max(65_535),
        label: z.string().max(120).nullable(),
        selectedDurationSeconds: durationSchema,
        turnOn: z.boolean(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1CreateRuntimeWebService({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: {
            port: input.port,
            label: input.label,
            selected_duration_seconds: input.selectedDurationSeconds,
            turn_on: input.turnOn,
            operation_key: input.operationKey,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  update: publicProcedure
    .input(
      serviceSchema.merge(revisionSchema).extend({
        label: z.string().max(120).nullable().optional(),
        selectedDurationSeconds: durationSchema.optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const body = {
          expected_revision: input.expectedRevision,
          operation_key: input.operationKey,
          ...("label" in input ? { label: input.label } : {}),
          ...("selectedDurationSeconds" in input
            ? { selected_duration_seconds: input.selectedDurationSeconds }
            : {}),
        };
        const { data } = await runtimeWebV1UpdateRuntimeWebService({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            service_id: input.serviceId,
          },
          body,
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  turnOn: publicProcedure
    .input(
      serviceSchema.merge(revisionSchema).extend({
        selectedDurationSeconds: durationSchema.optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1TurnOnRuntimeWebService({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            service_id: input.serviceId,
          },
          body: {
            expected_revision: input.expectedRevision,
            operation_key: input.operationKey,
            selected_duration_seconds: input.selectedDurationSeconds,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  turnOnById: publicProcedure
    .input(
      z
        .object({ serviceId: z.string().length(32) })
        .merge(revisionSchema)
        .extend({
          selectedDurationSeconds: durationSchema,
        }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1TurnOnRuntimeWebServiceById({
          client: ctx.apiClient,
          path: { service_id: input.serviceId },
          body: {
            expected_revision: input.expectedRevision,
            operation_key: input.operationKey,
            selected_duration_seconds: input.selectedDurationSeconds,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  turnOff: publicProcedure
    .input(serviceSchema.merge(revisionSchema))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1TurnOffRuntimeWebService({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            service_id: input.serviceId,
          },
          body: {
            expected_revision: input.expectedRevision,
            operation_key: input.operationKey,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  reset: publicProcedure
    .input(serviceSchema.merge(revisionSchema))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1ResetRuntimeWebServiceExpiration({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            service_id: input.serviceId,
          },
          body: {
            expected_revision: input.expectedRevision,
            operation_key: input.operationKey,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  delete: publicProcedure
    .input(serviceSchema.merge(revisionSchema))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1DeleteRuntimeWebService({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            service_id: input.serviceId,
          },
          body: {
            expected_revision: input.expectedRevision,
            operation_key: input.operationKey,
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),
});
