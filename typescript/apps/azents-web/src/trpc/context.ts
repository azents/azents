/**
 * tRPC Context
 *
 * API client settings for communicating with azents public API.
 * - Refresh token and set Authorization header through interceptor
 * - Proactive refresh near expiration (5 minutes before)
 */
import {
  authV1RefreshToken,
  type Client,
  createClient,
  createConfig,
} from "@azents/public-client";
import { TRPCError } from "@trpc/server";
import { getServerConfig } from "@/config/server";
import {
  clearAuthCookiesToHeaders,
  getAccessToken,
  getRefreshToken,
  isTokenExpiringSoon,
  setAuthCookiesToHeaders,
} from "@/shared/lib/cookies";
import { safeFetch } from "@/shared/lib/safe-fetch";
import { ApiError, withApiErrorInterceptor } from "./api-error";

export { COOKIE_NAMES } from "@/shared/lib/cookies";

export interface Context {
  apiClient: Client;
  resHeaders: Headers;
}

/**
 * Attempt refresh when token is near expiration
 * @param client - API client (used without interceptor to prevent infinite loop)
 * @param resHeaders - response headers for setting cookies
 */
async function refreshTokenIfNeeded(
  client: Client,
  resHeaders: Headers,
): Promise<string | null> {
  const storedToken = await getAccessToken();
  const refreshToken = await getRefreshToken();

  // Use Access Token as-is when it exists and is not near expiration
  if (storedToken && !isTokenExpiringSoon(storedToken.expiresAt)) {
    return storedToken.token;
  }

  // Login required when Refresh Token is absent
  if (!refreshToken) {
    return null;
  }

  // Issue new Access Token with Refresh Token
  try {
    const response = await authV1RefreshToken({
      client,
      throwOnError: true,
      body: { refresh_token: refreshToken },
    });

    setAuthCookiesToHeaders(resHeaders, {
      accessToken: response.data.access_token,
      refreshToken: response.data.refresh_token,
      expiresInSeconds: response.data.expires_in,
    });

    return response.data.access_token;
  } catch (error) {
    // 401: refresh token expired/invalid → delete cookies, propagate UNAUTHORIZED (logout flow)
    if (error instanceof ApiError && error.status === 401) {
      clearAuthCookiesToHeaders(resHeaders);
      throw new TRPCError({
        code: "UNAUTHORIZED",
        message: "Session expired. Please log in again.",
      });
    }
    // Other errors (4xx/5xx/network): propagate original error
    throw error;
  }
}

function getInternalApiClientConfig(): ReturnType<typeof createConfig> {
  const config = getServerConfig();
  return createConfig({
    baseUrl: config.internalApiUrl,
    fetch: safeFetch,
  });
}

/** Route handler also obtains access token with same refresh policy as tRPC. */
export async function getFreshAccessToken(
  resHeaders: Headers,
): Promise<string | null> {
  const refreshClient = withApiErrorInterceptor(
    createClient(getInternalApiClientConfig()),
  );
  return refreshTokenIfNeeded(refreshClient, resHeaders);
}

/**
 * Create API client
 * - request Refresh token and set Authorization header through interceptor
 * @param resHeaders - response headers for setting cookies
 */
function getApiClient(resHeaders: Headers): Client {
  // Use safeFetch to bypass Next.js fetch patch.
  // See shared/lib/safe-fetch.ts for detailed reason.
  const clientConfig = getInternalApiClientConfig();

  // Token refresh client (no interceptor, prevents infinite loop)
  const refreshClient = withApiErrorInterceptor(createClient(clientConfig));

  // Main client
  const client = withApiErrorInterceptor(createClient(clientConfig));

  // Request interceptor: refresh token and add Authorization header
  client.interceptors.request.use(async (request) => {
    const accessToken = await refreshTokenIfNeeded(refreshClient, resHeaders);

    if (accessToken) {
      request.headers.set("Authorization", `Bearer ${accessToken}`);
    }

    return request;
  });

  return client;
}

/**
 * Context creation function
 * - Called for each HTTP request
 * @param resHeaders - response headers received from tRPC fetchRequestHandler
 */
export function createContext(resHeaders: Headers): Context {
  return {
    apiClient: getApiClient(resHeaders),
    resHeaders,
  };
}

/**
 * Create context for server-side caller
 * - Used when directly called from Server Component
 */
export function createServerContext(): Context {
  // Create empty Headers because Server Component has no resHeaders
  const resHeaders = new Headers();
  return createContext(resHeaders);
}

/** Create API client with access token already prepared in Route handler. */
export function createApiClientWithAccessToken(
  accessToken: string,
  options?: { cache?: RequestCache },
): Client {
  const config = getServerConfig();
  const fetch = options?.cache
    ? (input: RequestInfo | URL, init?: RequestInit) =>
        safeFetch(input, { ...init, cache: options.cache })
    : safeFetch;
  const client = withApiErrorInterceptor(
    createClient(
      createConfig({
        baseUrl: config.internalApiUrl,
        fetch,
      }),
    ),
  );
  client.interceptors.request.use((request) => {
    request.headers.set("Authorization", `Bearer ${accessToken}`);
    return request;
  });
  return client;
}
