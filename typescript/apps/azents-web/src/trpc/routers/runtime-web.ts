import {
  runtimeWebV1ApproveRuntimeWebRequest,
  runtimeWebV1ApproveRuntimeWebRequestByEndpointId,
  runtimeWebV1CancelRuntimeWebRequest,
  runtimeWebV1CancelRuntimeWebRequestByEndpointId,
  runtimeWebV1CloseRuntimeWebCycle,
  runtimeWebV1CloseRuntimeWebCycleByEndpointId,
  runtimeWebV1DirectCreateRuntimeWebExposure,
  runtimeWebV1GetRuntimeWebServiceProjection,
  runtimeWebV1GetServiceByEndpointId,
  runtimeWebV1ListRuntimeWebServices,
  runtimeWebV1PrepareRuntimeWebEndpoint,
  runtimeWebV1RejectRuntimeWebRequest,
  runtimeWebV1RejectRuntimeWebRequestByEndpointId,
  runtimeWebV1RequestRuntimeWebExposure,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const resourceSchema = z.object({
  handle: z.string().min(1),
  agentId: z.string().min(1),
  sessionId: z.string().min(1),
});
const serviceSchema = resourceSchema.extend({
  port: z.number().int().min(1).max(65_535),
});
const endpointSchema = z.object({ endpointId: z.string().length(32) });
const requestDecisionSchema = z.object({
  requestId: z.string().min(1),
  expectedRevision: z.number().int().min(1),
});
const approvalSchema = requestDecisionSchema.extend({
  durationSeconds: z.number().int().min(300).max(28_800),
  durationRevision: z.number().int().min(1),
});

const expectedErrors = {
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  409: "CONFLICT",
  429: "TOO_MANY_REQUESTS",
} as const;

function operationKey(): string {
  return crypto.randomUUID();
}

export const runtimeWebRouter = router({
  list: publicProcedure.input(resourceSchema).query(async ({ ctx, input }) => {
    try {
      const { data } = await runtimeWebV1ListRuntimeWebServices({
        client: ctx.apiClient,
        path: {
          handle: input.handle,
          agent_id: input.agentId,
          session_id: input.sessionId,
        },
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
          session_id: input.sessionId,
          port: input.port,
        },
        throwOnError: true,
      });
      return data;
    } catch (error) {
      throw mapExpectedError(error, expectedErrors);
    }
  }),

  getByEndpointId: publicProcedure
    .input(endpointSchema)
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1GetServiceByEndpointId({
          client: ctx.apiClient,
          path: { endpoint_id: input.endpointId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  prepare: publicProcedure
    .input(serviceSchema.extend({ label: z.string().max(120).nullable() }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1PrepareRuntimeWebEndpoint({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
            port: input.port,
          },
          body: { label: input.label, operation_key: operationKey() },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  request: publicProcedure
    .input(serviceSchema.extend({ label: z.string().max(120).nullable() }))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1RequestRuntimeWebExposure({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
            port: input.port,
          },
          body: { label: input.label, operation_key: operationKey() },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  directCreate: publicProcedure
    .input(
      serviceSchema.extend({
        label: z.string().max(120).nullable(),
        durationSeconds: z.number().int().min(300).max(28_800),
        durationRevision: z.number().int().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1DirectCreateRuntimeWebExposure({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
            port: input.port,
          },
          body: {
            label: input.label,
            duration_seconds: input.durationSeconds,
            duration_configuration_revision: input.durationRevision,
            operation_key: operationKey(),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  approve: publicProcedure
    .input(resourceSchema.merge(approvalSchema))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1ApproveRuntimeWebRequest({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
            request_id: input.requestId,
          },
          body: {
            expected_revision: input.expectedRevision,
            duration_seconds: input.durationSeconds,
            duration_configuration_revision: input.durationRevision,
            operation_key: operationKey(),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  approveByEndpointId: publicProcedure
    .input(endpointSchema.merge(approvalSchema))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1ApproveRuntimeWebRequestByEndpointId(
          {
            client: ctx.apiClient,
            path: {
              endpoint_id: input.endpointId,
              request_id: input.requestId,
            },
            body: {
              expected_revision: input.expectedRevision,
              duration_seconds: input.durationSeconds,
              duration_configuration_revision: input.durationRevision,
              operation_key: operationKey(),
            },
            throwOnError: true,
          },
        );
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  reject: publicProcedure
    .input(resourceSchema.merge(requestDecisionSchema))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1RejectRuntimeWebRequest({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
            request_id: input.requestId,
          },
          body: {
            expected_revision: input.expectedRevision,
            operation_key: operationKey(),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  rejectByEndpointId: publicProcedure
    .input(endpointSchema.merge(requestDecisionSchema))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1RejectRuntimeWebRequestByEndpointId({
          client: ctx.apiClient,
          path: {
            endpoint_id: input.endpointId,
            request_id: input.requestId,
          },
          body: {
            expected_revision: input.expectedRevision,
            operation_key: operationKey(),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  cancel: publicProcedure
    .input(resourceSchema.merge(requestDecisionSchema))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1CancelRuntimeWebRequest({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
            request_id: input.requestId,
          },
          body: {
            expected_revision: input.expectedRevision,
            operation_key: operationKey(),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  cancelByEndpointId: publicProcedure
    .input(endpointSchema.merge(requestDecisionSchema))
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1CancelRuntimeWebRequestByEndpointId({
          client: ctx.apiClient,
          path: {
            endpoint_id: input.endpointId,
            request_id: input.requestId,
          },
          body: {
            expected_revision: input.expectedRevision,
            operation_key: operationKey(),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  close: publicProcedure
    .input(
      resourceSchema.extend({
        cycleId: z.string().min(1),
        expectedEndpointRevision: z.number().int().min(0),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1CloseRuntimeWebCycle({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            session_id: input.sessionId,
            cycle_id: input.cycleId,
          },
          body: {
            expected_endpoint_revision: input.expectedEndpointRevision,
            operation_key: operationKey(),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),

  closeByEndpointId: publicProcedure
    .input(
      endpointSchema.extend({
        cycleId: z.string().min(1),
        expectedEndpointRevision: z.number().int().min(0),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await runtimeWebV1CloseRuntimeWebCycleByEndpointId({
          client: ctx.apiClient,
          path: {
            endpoint_id: input.endpointId,
            cycle_id: input.cycleId,
          },
          body: {
            expected_endpoint_revision: input.expectedEndpointRevision,
            operation_key: operationKey(),
          },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, expectedErrors);
      }
    }),
});
