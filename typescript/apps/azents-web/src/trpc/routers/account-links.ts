import {
  externalChannelV1CancelAccountLinkCandidate,
  externalChannelV1ConfirmAccountLinkCandidate,
  externalChannelV1CreateAccountLinkCandidate,
  externalChannelV1ExchangeAccountLinkOauth,
  externalChannelV1GetAccountLinkCandidate,
  externalChannelV1GetAccountLinkOrigin,
  externalChannelV1ListAccountLinks,
  externalChannelV1StartAccountLinkOauth,
  externalChannelV1UnlinkAccountLink,
} from "@azents/public-client";
import { z } from "zod/v4";
import { accountLinkFailureReason } from "../account-link-error";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

function unexpectedAccountLinkError(error: unknown): unknown {
  return mapExpectedError(error, {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    410: "BAD_REQUEST",
    503: "SERVICE_UNAVAILABLE",
  });
}

function markPrivateNoStore(headers: Headers): void {
  headers.set("Cache-Control", "private, no-store");
}

export const accountLinksRouter = router({
  list: publicProcedure.query(async ({ ctx }) => {
    try {
      markPrivateNoStore(ctx.resHeaders);
      const { data } = await externalChannelV1ListAccountLinks({
        client: ctx.apiClient,
        throwOnError: true,
      });
      return data;
    } catch (error) {
      throw unexpectedAccountLinkError(error);
    }
  }),

  startOauth: publicProcedure
    .input(z.object({ provider: z.enum(["slack", "discord"]) }))
    .mutation(async ({ ctx, input }) => {
      try {
        markPrivateNoStore(ctx.resHeaders);
        const { data } = await externalChannelV1StartAccountLinkOauth({
          client: ctx.apiClient,
          path: { provider: input.provider },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw unexpectedAccountLinkError(error);
      }
    }),

  exchangeOauth: publicProcedure
    .input(
      z.object({
        provider: z.enum(["slack", "discord"]),
        code: z.string().min(1).max(2048),
        state: z.string().min(1).max(512),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        markPrivateNoStore(ctx.resHeaders);
        const { data } = await externalChannelV1ExchangeAccountLinkOauth({
          client: ctx.apiClient,
          path: { provider: input.provider },
          body: { code: input.code, state: input.state },
          throwOnError: true,
        });
        return data;
      } catch (error) {
        throw unexpectedAccountLinkError(error);
      }
    }),

  unlink: publicProcedure
    .input(z.object({ linkId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        markPrivateNoStore(ctx.resHeaders);
        const { data } = await externalChannelV1UnlinkAccountLink({
          client: ctx.apiClient,
          path: { link_id: input.linkId },
          throwOnError: true,
        });
        return { type: "SUCCESS" as const, data };
      } catch (error) {
        const reason = accountLinkFailureReason(error);
        if (reason !== null) {
          return { type: "FAILURE" as const, reason };
        }
        throw unexpectedAccountLinkError(error);
      }
    }),

  getOrigin: publicProcedure
    .input(z.object({ originId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        markPrivateNoStore(ctx.resHeaders);
        const { data } = await externalChannelV1GetAccountLinkOrigin({
          client: ctx.apiClient,
          path: { origin_id: input.originId },
          throwOnError: true,
        });
        return { type: "SUCCESS" as const, data };
      } catch (error) {
        const reason = accountLinkFailureReason(error);
        if (reason !== null) {
          return { type: "FAILURE" as const, reason };
        }
        throw unexpectedAccountLinkError(error);
      }
    }),

  createCandidate: publicProcedure
    .input(z.object({ originId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        markPrivateNoStore(ctx.resHeaders);
        const { data } = await externalChannelV1CreateAccountLinkCandidate({
          client: ctx.apiClient,
          path: { origin_id: input.originId },
          throwOnError: true,
        });
        return { type: "SUCCESS" as const, data };
      } catch (error) {
        const reason = accountLinkFailureReason(error);
        if (reason !== null) {
          return { type: "FAILURE" as const, reason };
        }
        throw unexpectedAccountLinkError(error);
      }
    }),

  getCandidate: publicProcedure
    .input(z.object({ candidateId: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        markPrivateNoStore(ctx.resHeaders);
        const { data } = await externalChannelV1GetAccountLinkCandidate({
          client: ctx.apiClient,
          path: { candidate_id: input.candidateId },
          throwOnError: true,
        });
        return { type: "SUCCESS" as const, data };
      } catch (error) {
        const reason = accountLinkFailureReason(error);
        if (reason !== null) {
          return { type: "FAILURE" as const, reason };
        }
        throw unexpectedAccountLinkError(error);
      }
    }),

  confirmCandidate: publicProcedure
    .input(z.object({ candidateId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        markPrivateNoStore(ctx.resHeaders);
        const { data } = await externalChannelV1ConfirmAccountLinkCandidate({
          client: ctx.apiClient,
          path: { candidate_id: input.candidateId },
          throwOnError: true,
        });
        return { type: "SUCCESS" as const, data };
      } catch (error) {
        const reason = accountLinkFailureReason(error);
        if (reason !== null) {
          return { type: "FAILURE" as const, reason };
        }
        throw unexpectedAccountLinkError(error);
      }
    }),

  cancelCandidate: publicProcedure
    .input(z.object({ candidateId: z.string().min(1) }))
    .mutation(async ({ ctx, input }) => {
      try {
        markPrivateNoStore(ctx.resHeaders);
        const { data } = await externalChannelV1CancelAccountLinkCandidate({
          client: ctx.apiClient,
          path: { candidate_id: input.candidateId },
          throwOnError: true,
        });
        return { type: "SUCCESS" as const, data };
      } catch (error) {
        const reason = accountLinkFailureReason(error);
        if (reason !== null) {
          return { type: "FAILURE" as const, reason };
        }
        throw unexpectedAccountLinkError(error);
      }
    }),
});
