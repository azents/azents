import * as Sentry from "@sentry/nextjs";
import { type NextRequest, NextResponse } from "next/server";

interface RouteLogFields {
  status?: number;
  durationMs?: number;
  error?: unknown;
}

type RouteHandler<TContext> = (
  request: NextRequest,
  context: TContext,
) => Promise<Response>;

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  return "Unknown error";
}

function serializeError(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack,
    };
  }
  return { message: getErrorMessage(error) };
}

function logRouteServerError(
  route: string,
  method: string,
  fields: RouteLogFields,
): void {
  console.error(`Route ${method} ${route} failed`, {
    status: fields.status,
    durationMs: fields.durationMs,
    error: serializeError(fields.error),
  });

  Sentry.captureException(fields.error, {
    extra: {
      route,
      method,
      status: fields.status,
      durationMs: fields.durationMs,
    },
  });
}

export function withRouteLogging<TContext>(
  route: string,
  handler: RouteHandler<TContext>,
): RouteHandler<TContext> {
  return async (request, context) => {
    const start = Date.now();

    try {
      const response = await handler(request, context);
      return response;
    } catch (error) {
      logRouteServerError(route, request.method, {
        status: 500,
        durationMs: Date.now() - start,
        error,
      });
      return NextResponse.json(
        { error: "Internal server error" },
        { status: 500 },
      );
    }
  };
}
