import { chatV1FinalizeFileUploadForAgent } from "@azents/public-client";
import { TRPCError } from "@trpc/server";
import { type NextRequest, NextResponse } from "next/server";
import { rejectUntrustedMainWebOrigin } from "@/shared/lib/request-origin";
import { withRouteLogging } from "@/shared/lib/route-logging";
import {
  createApiClientWithAccessToken,
  getFreshAccessToken,
} from "@/trpc/context";

const ROUTE = "/api/chat/upload/[uploadId]/finalize";

interface FinalizeUploadRequest {
  agentId: string;
}

function isFinalizeUploadRequest(
  value: unknown,
): value is FinalizeUploadRequest {
  return (
    typeof value === "object" &&
    value !== null &&
    "agentId" in value &&
    typeof value.agentId === "string"
  );
}

async function readFinalizeUploadRequest(
  request: NextRequest,
  headers: Headers,
): Promise<FinalizeUploadRequest | NextResponse> {
  let body: unknown;
  try {
    body = await request.json();
  } catch (error) {
    if (error instanceof SyntaxError) {
      return NextResponse.json(
        { error: "Invalid upload finalize request" },
        { status: 400, headers },
      );
    }
    throw error;
  }
  if (!isFinalizeUploadRequest(body)) {
    return NextResponse.json(
      { error: "Invalid upload finalize request" },
      { status: 400, headers },
    );
  }
  return body;
}

async function post(
  request: NextRequest,
  { params }: { params: Promise<{ uploadId: string }> },
): Promise<NextResponse> {
  const rejection = rejectUntrustedMainWebOrigin(request);
  if (rejection !== null) {
    return new NextResponse(rejection.body, {
      status: rejection.status,
      headers: rejection.headers,
    });
  }

  const responseHeaders = new Headers({ "Cache-Control": "no-store" });
  const body = await readFinalizeUploadRequest(request, responseHeaders);
  if (body instanceof NextResponse) {
    return body;
  }

  let accessToken: string | null;
  try {
    accessToken = await getFreshAccessToken(responseHeaders);
  } catch (error) {
    if (error instanceof TRPCError && error.code === "UNAUTHORIZED") {
      return NextResponse.json(
        { error: "Unauthorized" },
        { status: 401, headers: responseHeaders },
      );
    }
    throw error;
  }
  if (accessToken === null) {
    return NextResponse.json(
      { error: "Unauthorized" },
      { status: 401, headers: responseHeaders },
    );
  }

  const { uploadId } = await params;
  const { data, error, response } = await chatV1FinalizeFileUploadForAgent({
    client: createApiClientWithAccessToken(accessToken),
    path: { agent_id: body.agentId, upload_id: uploadId },
    throwOnError: false,
  });
  if (!response) {
    throw new Error("Upload finalize completed without a backend response.");
  }
  if (!response.ok) {
    return NextResponse.json(error ?? { error: "Upload finalize failed" }, {
      status: response.status,
      headers: responseHeaders,
    });
  }
  if (!data) {
    throw new Error("Upload finalize completed without a response body.");
  }

  return NextResponse.json(data, { headers: responseHeaders });
}

export const POST = withRouteLogging(ROUTE, post);
