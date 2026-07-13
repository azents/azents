import { type Client as AdminApiClient } from "@azents/admin-client";
import { authV1RefreshToken } from "@azents/public-client";
import {
  createAdminApiClient,
  createPublicApiClient,
} from "@/shared/lib/api-clients";
import {
  clearAdminAuthCookies,
  getAdminAccessToken,
  getAdminRefreshToken,
  isAdminAccessTokenExpiringSoon,
  setAdminAuthCookies,
} from "@/shared/lib/auth-cookies";
import { withApiErrorInterceptor } from "./api-error";

export interface Context {
  accessToken: string | null;
  adminApiClient: AdminApiClient | null;
  authenticated: boolean;
  responseHeaders: Headers;
}

async function getFreshAccessToken(
  responseHeaders: Headers,
): Promise<string | null> {
  const storedToken = await getAdminAccessToken();
  if (storedToken && !isAdminAccessTokenExpiringSoon(storedToken.expiresAt)) {
    return storedToken.token;
  }

  const refreshToken = await getAdminRefreshToken();
  if (!refreshToken) {
    return null;
  }

  const response = await authV1RefreshToken({
    client: createPublicApiClient(),
    body: { refresh_token: refreshToken },
  });
  if (response.data) {
    setAdminAuthCookies(responseHeaders, {
      accessToken: response.data.access_token,
      refreshToken: response.data.refresh_token,
      expiresInSeconds: response.data.expires_in,
    });
    return response.data.access_token;
  }

  const status = response.response?.status ?? 502;
  if (status === 401) {
    clearAdminAuthCookies(responseHeaders);
    return null;
  }
  throw new Error(`Public API token refresh failed with status ${status}.`);
}

export async function createContext(
  responseHeaders: Headers,
): Promise<Context> {
  const accessToken = await getFreshAccessToken(responseHeaders);
  return {
    accessToken,
    adminApiClient: accessToken
      ? withApiErrorInterceptor(createAdminApiClient(accessToken))
      : null,
    authenticated: accessToken !== null,
    responseHeaders,
  };
}

export async function createServerContext(): Promise<Context> {
  return createContext(new Headers());
}
