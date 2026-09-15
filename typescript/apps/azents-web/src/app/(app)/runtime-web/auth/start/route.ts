import {
  runtimeWebV1GetRuntimeWebServiceById,
  runtimeWebV1InitiateRuntimeWebSeparateIdentity,
  runtimeWebV1IssueRuntimeWebSharedIdentity,
} from "@azents/public-client";
import { TRPCError } from "@trpc/server";
import { NextRequest, NextResponse } from "next/server";
import { rejectUntrustedMainWebOrigin } from "@/shared/lib/request-origin";
import {
  encodeMainBinding,
  RUNTIME_WEB_MAIN_BINDING_COOKIE,
  runtimeWebConfiguration,
} from "@/shared/lib/runtime-web-auth";
import {
  createApiClientWithAccessToken,
  getFreshAccessToken,
} from "@/trpc/context";

interface StartRequest {
  serviceId: string;
}

function isStartRequest(value: unknown): value is StartRequest {
  return (
    typeof value === "object" &&
    value !== null &&
    "serviceId" in value &&
    typeof value.serviceId === "string" &&
    /^[a-zA-Z0-9_-]{32}$/.test(value.serviceId)
  );
}

function unauthorized(headers: Headers): NextResponse {
  return NextResponse.json(
    { error: "Authentication required" },
    { status: 401, headers },
  );
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const rejection = rejectUntrustedMainWebOrigin(request);
  if (rejection !== null) {
    return NextResponse.json({ error: "Forbidden origin" }, { status: 403 });
  }
  const configuration = runtimeWebConfiguration();
  if (configuration.type === "DISABLED") {
    return NextResponse.json(
      { error: "Runtime Web Gateway is not configured" },
      { status: 409 },
    );
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch (error) {
    if (error instanceof SyntaxError) {
      return NextResponse.json({ error: "Invalid service" }, { status: 400 });
    }
    throw error;
  }
  if (!isStartRequest(body)) {
    return NextResponse.json({ error: "Invalid service" }, { status: 400 });
  }
  const resHeaders = new Headers({ "Cache-Control": "no-store" });
  let accessToken: string | null;
  try {
    accessToken = await getFreshAccessToken(resHeaders);
  } catch (error) {
    if (error instanceof TRPCError && error.code === "UNAUTHORIZED") {
      return unauthorized(resHeaders);
    }
    throw error;
  }
  if (accessToken === null) {
    return unauthorized(resHeaders);
  }
  const client = createApiClientWithAccessToken(accessToken);
  const { data: service } = await runtimeWebV1GetRuntimeWebServiceById({
    client,
    path: { service_id: body.serviceId },
    throwOnError: true,
  });
  if (service.url === null) {
    return NextResponse.json(
      { error: "Runtime Web Gateway is not configured" },
      { status: 409, headers: resHeaders },
    );
  }

  if (configuration.authMode === "shared_cookie") {
    const { data: identity } = await runtimeWebV1IssueRuntimeWebSharedIdentity({
      client,
      throwOnError: true,
    });
    const response = NextResponse.json(
      { mode: "shared_cookie", destination: service.url },
      { headers: resHeaders },
    );
    response.cookies.set(configuration.identityCookieName, identity.secret, {
      domain: configuration.cookieDomain,
      expires: new Date(identity.expires_at),
      httpOnly: true,
      secure: true,
      sameSite: "strict",
      path: "/",
    });
    return response;
  }

  const { data: initiation } =
    await runtimeWebV1InitiateRuntimeWebSeparateIdentity({
      client,
      body: { service_id: body.serviceId },
      throwOnError: true,
    });
  const response = NextResponse.json(
    {
      mode: "separate_domain",
      brokerDestination: `${configuration.brokerOrigin}/bind`,
      initiationId: initiation.initiation_id,
    },
    { headers: resHeaders },
  );
  response.cookies.set(
    RUNTIME_WEB_MAIN_BINDING_COOKIE,
    encodeMainBinding(initiation.initiation_id, initiation.main_binding_secret),
    {
      expires: new Date(initiation.expires_at),
      httpOnly: true,
      secure: true,
      sameSite: "none",
      path: "/",
    },
  );
  return response;
}
