import { TRPCError } from "@trpc/server";
/**
 * API error utilities
 *
 * Preserves HTTP status codes through hey-api error interceptor,
 * and selectively converts only expected errors in tRPC router.
 */
import type { Client } from "@azents/public-client";

export type TRPCErrorCode = ConstructorParameters<typeof TRPCError>[0]["code"];

/** API server HTTP error (status code + response body included) */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(extractDetail(body));
    this.name = "ApiError";
  }
}

/** Extract detail message from API error body */
function extractDetail(error: unknown): string {
  // FastAPI validation error (array body: [{code, message, ...}])
  if (Array.isArray(error)) {
    return (
      error
        .map((d: { message?: string }) => d.message)
        .filter(Boolean)
        .join(", ") || "Invalid input."
    );
  }
  if (typeof error === "object" && error !== null && "detail" in error) {
    const { detail } = error;
    if (typeof detail === "string") {
      return detail;
    }
    // FastAPI validation error ({detail: [{msg, ...}]})
    if (Array.isArray(detail)) {
      return (
        detail
          .map((d: { msg?: string }) => d.msg)
          .filter(Boolean)
          .join(", ") || "Invalid input."
      );
    }
    // If detail is structured object, serialize JSON (downstream can parse it)
    if (typeof detail === "object" && detail !== null) {
      const msg = "message" in detail ? detail.message : null;
      if (typeof msg === "string") {
        return JSON.stringify(detail);
      }
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "An unknown error occurred.";
}

/**
 * Register error interceptor on API client.
 *
 * Wrap HTTP error response as ApiError and preserve status code.
 * Network errors pass through as original.
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
 * Convert expected HTTP errors to TRPCError.
 *
 * status code included in expected → convert to corresponding tRPC code,
 * otherwise → return original error as-is (tRPC handles as INTERNAL_SERVER_ERROR).
 */
export function mapExpectedError(
  error: unknown,
  expected: Partial<Record<number, TRPCErrorCode>>,
): unknown {
  if (error instanceof ApiError) {
    const code = expected[error.status];
    if (code) {
      return new TRPCError({ code, message: error.message, cause: error });
    }
  }
  return error;
}
