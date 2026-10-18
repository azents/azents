import { TRPCError } from "@trpc/server";
import { z } from "zod/v4";
/**
 * API error utilities
 *
 * Preserves HTTP status codes with a hey-api error interceptor and
 * selectively converts expected errors in tRPC routers.
 */
import type { Client } from "@azents/admin-client";

type TRPCErrorCode = ConstructorParameters<typeof TRPCError>[0]["code"];
const validationMessageSchema = z.object({ message: z.string() });
const validationDetailSchema = z.object({ msg: z.string() });

/** Project only validated messages; malformed array entries carry no message. */
function validationMessages(
  entries: unknown[],
  field: "message" | "msg",
): string {
  const messages = entries.flatMap((entry) => {
    if (field === "message") {
      const result = validationMessageSchema.safeParse(entry);
      return result.success ? [result.data.message] : [];
    }
    const result = validationDetailSchema.safeParse(entry);
    return result.success ? [result.data.msg] : [];
  });
  return messages.filter(Boolean).join(", ") || "The input is invalid.";
}

/** API server HTTP error (including status code and response body) */
export class ApiError extends Error {
  public readonly status: number;
  public readonly body: unknown;
  constructor(status: number, body: unknown) {
    super(extractDetail(body));
    this.status = status;
    this.body = body;
    this.name = "ApiError";
  }
}

/** Extract the detail message from an API error body */
function extractDetail(error: unknown): string {
  // FastAPI validation error (array body: [{code, message, ...}])
  if (Array.isArray(error)) {
    return validationMessages(error, "message");
  }
  if (typeof error === "object" && error !== null && "detail" in error) {
    const { detail } = error;
    if (typeof detail === "string") {
      return detail;
    }
    // FastAPI validation error ({detail: [{msg, ...}]})
    if (Array.isArray(detail)) {
      return validationMessages(detail, "msg");
    }
    // Serialize structured detail objects as JSON so downstream code can parse them
    if (typeof detail === "object" && detail !== null) {
      const msg = "message" in detail ? detail.message : null;
      if (typeof msg === "string") {
        return JSON.stringify(detail);
      }
      return JSON.stringify(detail);
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "An unknown error occurred.";
}

/**
 * Registers an error interceptor on the API client.
 *
 * Wraps HTTP error responses in ApiError to preserve the status code.
 * Passes network errors through unchanged.
 */
export function withApiErrorInterceptor(client: Client): Client {
  client.interceptors.error.use((error, response) => {
    if (response instanceof Response) {
      return new ApiError(response.status, error);
    }
    return error;
  });
  return client;
}

/**
 * Converts expected HTTP errors to TRPCError instances.
 *
 * Status codes included in expected are converted to the corresponding tRPC code;
 * all others return the original error for tRPC to handle as INTERNAL_SERVER_ERROR.
 */
export function mapExpectedError(
  error: unknown,
  expected: Partial<Record<number, TRPCErrorCode>>,
): unknown {
  if (error instanceof ApiError) {
    const code = expected[error.status];
    if (code) {
      return new TRPCError({ code, message: error.message });
    }
  }
  return error;
}
