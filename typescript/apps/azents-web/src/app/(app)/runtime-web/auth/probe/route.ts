import { NextRequest, NextResponse } from "next/server";
import { rejectUntrustedMainWebOrigin } from "@/shared/lib/request-origin";
import {
  RUNTIME_WEB_HTTP_PROBE_COOKIE,
  RUNTIME_WEB_ORDINARY_PROBE_COOKIE,
} from "@/shared/lib/runtime-web-auth";

interface ProbeRequest {
  phase: "reset" | "verify";
}

function isProbeRequest(value: unknown): value is ProbeRequest {
  if (typeof value !== "object" || value === null || !("phase" in value)) {
    return false;
  }
  return value.phase === "reset" || value.phase === "verify";
}

function clearHttpProbe(response: NextResponse): void {
  response.cookies.set(RUNTIME_WEB_HTTP_PROBE_COOKIE, "", {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const rejection = rejectUntrustedMainWebOrigin(request);
  if (rejection !== null) {
    return NextResponse.json({ error: "Forbidden origin" }, { status: 403 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch (error) {
    if (error instanceof SyntaxError) {
      return NextResponse.json(
        { error: "Invalid probe request" },
        { status: 400 },
      );
    }
    throw error;
  }
  if (!isProbeRequest(body)) {
    return NextResponse.json(
      { error: "Invalid probe request" },
      { status: 400 },
    );
  }
  const response = NextResponse.json(
    { ready: true },
    { headers: { "Cache-Control": "no-store" } },
  );
  if (body.phase === "reset") {
    clearHttpProbe(response);
    return response;
  }
  if (
    request.cookies.get(RUNTIME_WEB_ORDINARY_PROBE_COOKIE)?.value !== "ready" ||
    request.cookies.has(RUNTIME_WEB_HTTP_PROBE_COOKIE)
  ) {
    return NextResponse.json(
      { error: "Required browser cookie protections are unavailable" },
      { status: 426, headers: { "Cache-Control": "no-store" } },
    );
  }
  response.cookies.set(RUNTIME_WEB_HTTP_PROBE_COOKIE, "ready", {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 120,
  });
  return response;
}
