/**
 * Exchange authenticated download redirect route.
 *
 * Inject the API token for metadata only; the browser retrieves bytes from S3.
 */
import { chatV1DownloadExchangeFile } from "@azents/public-client";
import { TRPCError } from "@trpc/server";
import { type NextRequest, NextResponse } from "next/server";
import { browserDownloadRedirect } from "@/shared/file-upload/browserDownloadRedirect";
import { withRouteLogging } from "@/shared/lib/route-logging";
import {
  createApiClientWithAccessToken,
  getFreshAccessToken,
} from "@/trpc/context";

const ROUTE = "/api/chat/exchange-files/[fileId]/download";
async function get(
  request: NextRequest,
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
    query: {
      disposition:
        request.nextUrl.searchParams.get("disposition") === "inline"
          ? "inline"
          : "attachment",
    },
    redirect: "manual",
    parseAs: "text",
  });

  if (!response) {
    throw new Error("Exchange file download failed without backend response.");
  }
  return browserDownloadRedirect(response, resHeaders);
}

export const GET = withRouteLogging(ROUTE, get);
