import {
  externalChannelV1DecideApprovalRequest,
  externalChannelV1GetApprovalRequest,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const approvalDecisionSchema = z.enum([
  "allow_session",
  "allow_agent",
  "deny",
  "block",
]);

export const externalChannelRouter = router({
  getApprovalRequest: publicProcedure
    .input(z.object({ accessRequestId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1GetApprovalRequest({
          client: ctx.apiClient,
          path: { access_request_id: input.accessRequestId },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
        });
      }
    }),

  decideApprovalRequest: publicProcedure
    .input(
      z.object({
        accessRequestId: z.string().min(1),
        decision: approvalDecisionSchema,
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await externalChannelV1DecideApprovalRequest({
          client: ctx.apiClient,
          path: { access_request_id: input.accessRequestId },
          body: { decision: input.decision },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw mapExpectedError(error, {
          401: "UNAUTHORIZED",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),
});
