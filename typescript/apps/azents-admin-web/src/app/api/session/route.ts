import { systemV1GetSystemAdminMe } from "@azents/admin-client";
import { authV1LoginWithPassword, authV1Logout } from "@azents/public-client";
import { z } from "zod/v4";
import {
  createAdminApiClient,
  createAuthenticatedPublicApiClient,
  createPublicApiClient,
} from "@/shared/lib/api-clients";
import {
  clearAdminAuthCookies,
  setAdminAuthCookies,
} from "@/shared/lib/auth-cookies";
import { hasExpectedOrigin } from "@/shared/lib/same-origin";
import { createContext } from "@/trpc/context";

const LoginInputSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

function responseStatus(response?: Response): number {
  return response?.status ?? 502;
}

function errorResponse(
  status: number,
  message: string,
  headers?: Headers,
): Response {
  return Response.json({ error: message }, { status, headers });
}

export async function GET(): Promise<Response> {
  const responseHeaders = new Headers();
  const context = await createContext(responseHeaders);
  if (!context.adminApiClient) {
    return errorResponse(
      401,
      "Admin session is not authenticated.",
      responseHeaders,
    );
  }

  const admin = await systemV1GetSystemAdminMe({
    client: context.adminApiClient,
  });
  if (!admin.data) {
    const status = responseStatus(admin.response);
    if (status === 401 || status === 403) {
      clearAdminAuthCookies(responseHeaders);
    }
    return errorResponse(
      status,
      status === 403
        ? "System administrator access is required."
        : "Admin session validation failed.",
      responseHeaders,
    );
  }

  return Response.json(admin.data, { headers: responseHeaders });
}

export async function POST(request: Request): Promise<Response> {
  if (!hasExpectedOrigin(request)) {
    return errorResponse(403, "A same-origin request is required.");
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch (error) {
    if (error instanceof SyntaxError) {
      return errorResponse(400, "A valid JSON request body is required.");
    }
    throw error;
  }
  const parsedInput = LoginInputSchema.safeParse(body);
  if (!parsedInput.success) {
    return errorResponse(400, "A valid email and password are required.");
  }

  const login = await authV1LoginWithPassword({
    client: createPublicApiClient(),
    body: parsedInput.data,
  });
  if (!login.data) {
    const status = responseStatus(login.response);
    return errorResponse(
      status === 401 ? 401 : 400,
      "Email or password is incorrect.",
    );
  }

  const admin = await systemV1GetSystemAdminMe({
    client: createAdminApiClient(login.data.access_token),
  });
  if (!admin.data) {
    await authV1Logout({
      client: createAuthenticatedPublicApiClient(login.data.access_token),
    });
    const status = responseStatus(admin.response);
    return errorResponse(
      status === 403 ? 403 : 401,
      status === 403
        ? "This account is not a system administrator."
        : "Admin session validation failed.",
    );
  }

  const responseHeaders = new Headers();
  setAdminAuthCookies(responseHeaders, {
    accessToken: login.data.access_token,
    refreshToken: login.data.refresh_token,
    expiresInSeconds: login.data.expires_in,
  });
  return Response.json(admin.data, { headers: responseHeaders });
}

export async function DELETE(request: Request): Promise<Response> {
  if (!hasExpectedOrigin(request)) {
    return errorResponse(403, "A same-origin request is required.");
  }

  const responseHeaders = new Headers();
  const context = await createContext(responseHeaders);
  if (context.accessToken) {
    await authV1Logout({
      client: createAuthenticatedPublicApiClient(context.accessToken),
    });
  }
  clearAdminAuthCookies(responseHeaders);
  return new Response(null, { status: 204, headers: responseHeaders });
}
