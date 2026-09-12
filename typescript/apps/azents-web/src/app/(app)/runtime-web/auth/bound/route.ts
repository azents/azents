import {
  runtimeWebV1IssueRuntimeWebSeparateTicket,
  runtimeWebV1MarkRuntimeWebSeparateIdentityBound,
} from "@azents/public-client";
import { TRPCError } from "@trpc/server";
import { NextRequest, NextResponse } from "next/server";
import { hasExactRequestOrigin } from "@/shared/lib/request-origin";
import {
  decodeMainBinding,
  RUNTIME_WEB_MAIN_BINDING_COOKIE,
  runtimeWebConfiguration,
} from "@/shared/lib/runtime-web-auth";
import {
  createApiClientWithAccessToken,
  getFreshAccessToken,
} from "@/trpc/context";

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function errorResponse(message: string, status: number): NextResponse {
  return new NextResponse(
    `<!doctype html><meta charset="utf-8"><title>Runtime Web</title><h1>${escapeHtml(message)}</h1>`,
    {
      status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        "Content-Type": "text/html; charset=utf-8",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
      },
    },
  );
}

function appendResponseHeaders(target: Headers, source: Headers): void {
  source.forEach((value, name) => {
    if (name !== "set-cookie") {
      target.append(name, value);
    }
  });
  for (const value of source.getSetCookie()) {
    target.append("Set-Cookie", value);
  }
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const configuration = runtimeWebConfiguration();
  if (
    configuration.type === "DISABLED" ||
    !hasExactRequestOrigin(request, configuration.brokerOrigin) ||
    request.headers.get("content-type")?.split(";", 1)[0] !==
      "application/x-www-form-urlencoded"
  ) {
    return errorResponse(
      "Runtime Web authentication request was rejected.",
      403,
    );
  }
  const form = await request.formData();
  const initiationId = form.get("initiation_id");
  const encodedBinding = request.cookies.get(
    RUNTIME_WEB_MAIN_BINDING_COOKIE,
  )?.value;
  const binding =
    encodedBinding == null ? null : decodeMainBinding(encodedBinding);
  if (
    typeof initiationId !== "string" ||
    binding === null ||
    binding.initiationId !== initiationId
  ) {
    return errorResponse("Runtime Web authentication binding expired.", 409);
  }

  const resHeaders = new Headers();
  let accessToken: string | null;
  try {
    accessToken = await getFreshAccessToken(resHeaders);
  } catch (error) {
    if (error instanceof TRPCError && error.code === "UNAUTHORIZED") {
      return errorResponse("Authentication required.", 401);
    }
    throw error;
  }
  if (accessToken === null) {
    return errorResponse("Authentication required.", 401);
  }
  const client = createApiClientWithAccessToken(accessToken);
  const body = {
    initiation_id: initiationId,
    main_binding_secret: binding.secret,
  };
  await runtimeWebV1MarkRuntimeWebSeparateIdentityBound({
    client,
    body,
    throwOnError: true,
  });
  const { data: ticket } = await runtimeWebV1IssueRuntimeWebSeparateTicket({
    client,
    body,
    throwOnError: true,
  });
  const brokerDestination = `${configuration.brokerOrigin}/redeem`;
  const response = new NextResponse(
    [
      '<!doctype html><meta charset="utf-8"><title>Runtime Web</title>',
      `<form id="continue" method="post" action="${escapeHtml(brokerDestination)}">`,
      `<input type="hidden" name="ticket" value="${escapeHtml(ticket.ticket_secret)}">`,
      "</form>",
      '<script nonce="runtime-web">document.getElementById("continue").submit()</script>',
    ].join(""),
    {
      headers: {
        "Cache-Control": "no-store",
        "Content-Security-Policy": `default-src 'none'; script-src 'nonce-runtime-web'; form-action ${configuration.brokerOrigin}; frame-ancestors 'none'`,
        "Content-Type": "text/html; charset=utf-8",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
      },
    },
  );
  appendResponseHeaders(response.headers, resHeaders);
  response.cookies.set(RUNTIME_WEB_MAIN_BINDING_COOKIE, "", {
    httpOnly: true,
    secure: true,
    sameSite: "none",
    path: "/",
    maxAge: 0,
  });
  return response;
}
