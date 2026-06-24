/**
 * Agent workspace file download proxy route.
 *
 * Server proxies file response so browser never sees public API bearer token directly.
 */
import { chatV1DownloadAgentWorkspaceFile } from "@azents/public-client";
import { TRPCError } from "@trpc/server";
import { type NextRequest, NextResponse } from "next/server";
import { withRouteLogging } from "@/shared/lib/route-logging";
import {
  createApiClientWithAccessToken,
  getFreshAccessToken,
} from "@/trpc/context";

const ROUTE = "/api/chat/agents/[agentId]/workspace/download";

function copyHeaders(source: Headers, target: Headers): void {
  source.forEach((value, key) => {
    target.append(key, value);
  });
}

async function get(
  request: NextRequest,
  { params }: { params: Promise<{ agentId: string }> },
): Promise<NextResponse | Response> {
  const resHeaders = new Headers();
  let accessToken: string | null;
  try {
    accessToken = await getFreshAccessToken(resHeaders);
  } catch (error) {
    if (error instanceof TRPCError && error.code === "UNAUTHORIZED") {
      return NextResponse.json(
        { error: "Unauthorized" },
        { status: 401, headers: resHeaders },
      );
    }
    throw error;
  }
  if (!accessToken) {
    return NextResponse.json(
      { error: "Unauthorized" },
      { status: 401, headers: resHeaders },
    );
  }

  const path = request.nextUrl.searchParams.get("path");
  if (!path) {
    return NextResponse.json(
      { error: "Missing path" },
      { status: 400, headers: resHeaders },
    );
  }

  const { agentId } = await params;
  const { response } = await chatV1DownloadAgentWorkspaceFile({
    client: createApiClientWithAccessToken(accessToken),
    path: { agent_id: agentId },
    query: { path },
    parseAs: "stream",
  });

  if (!response) {
    throw new Error(
      "Agent workspace file download failed without backend response.",
    );
  }
  if (!response.ok) {
    return NextResponse.json(
      { error: "Failed to fetch agent workspace file" },
      { status: response.status, headers: resHeaders },
    );
  }

  const contentType =
    response.headers.get("content-type") ?? "application/octet-stream";
  const contentDisposition = response.headers.get("content-disposition");
  const body = await response.arrayBuffer();

  const headers = new Headers();
  headers.set("Content-Type", contentType);
  headers.set("Content-Length", String(body.byteLength));

  if (contentDisposition) {
    headers.set("Content-Disposition", contentDisposition);
  }

  copyHeaders(resHeaders, headers);

  return new Response(body, {
    status: 200,
    headers,
  });
}

export const GET = withRouteLogging(ROUTE, get);
