/**
 * Exchange file download proxy route.
 *
 * Expose only same-origin URL to browser and inject backend API token on server.
 */
import { chatV1DownloadExchangeFile } from "@azents/public-client";
import { TRPCError } from "@trpc/server";
import { type NextRequest, NextResponse } from "next/server";
import { withRouteLogging } from "@/shared/lib/route-logging";
import {
  createApiClientWithAccessToken,
  getFreshAccessToken,
} from "@/trpc/context";

const ROUTE = "/api/chat/exchange-files/[fileId]/download";

function copyHeaders(source: Headers, target: Headers): void {
  source.forEach((value, key) => {
    target.append(key, value);
  });
}

async function get(
  _request: NextRequest,
  { params }: { params: Promise<{ fileId: string }> },
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

  const { fileId } = await params;
  const { response } = await chatV1DownloadExchangeFile({
    client: createApiClientWithAccessToken(accessToken),
    path: { file_id: fileId },
    parseAs: "stream",
  });

  if (!response) {
    throw new Error("Exchange file download failed without backend response.");
  }
  if (!response.ok) {
    return NextResponse.json(
      { error: "Failed to fetch file" },
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
