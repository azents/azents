/**
 * File upload proxy route.
 *
 * Forward file received from client to backend API.
 */
import { TRPCError } from "@trpc/server";
import { NextRequest, NextResponse } from "next/server";
import { getServerConfig } from "@/config/server";
import { withRouteLogging } from "@/shared/lib/route-logging";
import { getFreshAccessToken } from "@/trpc/context";

const ROUTE = "/api/chat/upload";

async function parseJsonOrText(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { error: text };
  }
}

async function post(request: NextRequest): Promise<NextResponse> {
  const resHeaders = new Headers();

  const formData = await request.formData();
  const agentId = formData.get("agentId");
  const file = formData.get("file");

  if (!agentId || typeof agentId !== "string") {
    return NextResponse.json(
      { error: "Missing agentId" },
      { status: 400, headers: resHeaders },
    );
  }

  if (!file || !(file instanceof File)) {
    return NextResponse.json(
      { error: "Missing file" },
      { status: 400, headers: resHeaders },
    );
  }

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

  const backendFormData = new FormData();
  backendFormData.set("file", file, file.name);

  const config = getServerConfig();
  const uploadUrl = new URL(
    `/chat/v1/agents/${encodeURIComponent(agentId)}/upload`,
    config.internalApiUrl,
  );

  // generated client + safeFetch can break boundary while repacking multipart body
  // as arrayBuffer, so upload proxy passes FormData directly.
  const response = await fetch(uploadUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    body: backendFormData,
  });

  const body = await parseJsonOrText(response);
  return NextResponse.json(body, {
    status: response.status,
    headers: resHeaders,
  });
}

export const POST = withRouteLogging(ROUTE, post);
