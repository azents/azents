/**
 * Cookie utilities.
 *
 * Cookie management for azents-web authentication tokens.
 * - Store tokens in httpOnly cookies
 * - Support proactive refresh near expiration
 * - Set Set-Cookie headers through resHeaders (tRPC-compatible)
 */
import "server-only";
import { cookies } from "next/headers";
import { getServerConfig } from "@/config/server";
import { authCookiePolicy } from "./auth-cookie-policy";
import type { AuthCookieNames } from "./auth-cookie-policy";

export type { AuthCookieNames } from "./auth-cookie-policy";

export function getAuthCookieNames(): AuthCookieNames {
  const config = getServerConfig();
  return authCookiePolicy(config.nodeEnv, config.authCookiePolicyMode).names;
}

/** Access token information read from cookie */
export interface StoredAccessToken {
  token: string;
  expiresAt: number;
}

/** Information required when setting tokens */
export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  /** Access token expiration time (seconds) */
  expiresInSeconds: number;
}

/**
 * Read Access Token from cookie.
 * - Returns token and expiration time together.
 */
export async function getAccessToken(): Promise<StoredAccessToken | null> {
  const cookieStore = await cookies();
  const names = getAuthCookieNames();
  const token = cookieStore.get(names.ACCESS_TOKEN)?.value;
  const expiresAtStr = cookieStore.get(names.EXPIRES_AT)?.value;

  if (!token || !expiresAtStr) {
    return null;
  }

  const expiresAt = Number(expiresAtStr);
  if (Number.isNaN(expiresAt)) {
    return null;
  }

  return { token, expiresAt };
}

/**
 * Read Refresh Token from cookie.
 */
export async function getRefreshToken(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get(getAuthCookieNames().REFRESH_TOKEN)?.value ?? null;
}

/**
 * Check whether Access Token expires soon (within 5 minutes).
 */
export function isTokenExpiringSoon(expiresAt: number): boolean {
  const REFRESH_THRESHOLD = 5 * 60 * 1000; // 5 minutes
  return Date.now() + REFRESH_THRESHOLD >= expiresAt;
}

/**
 * Build Set-Cookie header string.
 */
function buildCookieString(
  name: string,
  value: string,
  options: {
    httpOnly?: boolean;
    secure?: boolean;
    sameSite?: "strict" | "lax" | "none";
    path?: string;
    maxAge?: number;
  },
): string {
  const parts = [`${name}=${value}`];

  if (options.path) {
    parts.push(`Path=${options.path}`);
  }
  if (options.maxAge != null) {
    parts.push(`Max-Age=${options.maxAge}`);
  }
  if (options.httpOnly) {
    parts.push("HttpOnly");
  }
  if (options.secure) {
    parts.push("Secure");
  }
  if (options.sameSite) {
    parts.push(
      `SameSite=${options.sameSite.charAt(0).toUpperCase()}${options.sameSite.slice(1)}`,
    );
  }

  return parts.join("; ");
}

/**
 * Set authentication cookies through Response Headers.
 * - Add Set-Cookie to tRPC resHeaders.
 */
export function setAuthCookiesToHeaders(
  resHeaders: Headers,
  tokens: AuthTokens,
): void {
  const config = getServerConfig();
  const policy = authCookiePolicy(config.nodeEnv, config.authCookiePolicyMode);
  const names = policy.names;
  const expiresAt = Date.now() + tokens.expiresInSeconds * 1000;

  const commonOptions = {
    httpOnly: true,
    secure: policy.secure,
    sameSite: policy.sameSite,
    path: "/",
  };

  // Access Token cookie (no maxAge — expiration is managed by EXPIRES_AT cookie)
  resHeaders.append(
    "Set-Cookie",
    buildCookieString(names.ACCESS_TOKEN, tokens.accessToken, commonOptions),
  );

  // Refresh Token cookie (30 days)
  resHeaders.append(
    "Set-Cookie",
    buildCookieString(names.REFRESH_TOKEN, tokens.refreshToken, {
      ...commonOptions,
      maxAge: 30 * 24 * 60 * 60,
    }),
  );

  // Expiration time cookie (httpOnly because JavaScript does not need to read it)
  resHeaders.append(
    "Set-Cookie",
    buildCookieString(names.EXPIRES_AT, String(expiresAt), commonOptions),
  );
}

/**
 * Delete authentication cookies through Response Headers.
 */
export function clearAuthCookiesToHeaders(resHeaders: Headers): void {
  const config = getServerConfig();
  const policy = authCookiePolicy(config.nodeEnv, config.authCookiePolicyMode);
  const names = policy.names;

  const clearOptions = {
    httpOnly: true,
    secure: policy.secure,
    sameSite: policy.sameSite,
    path: "/",
    maxAge: 0,
  };

  resHeaders.append(
    "Set-Cookie",
    buildCookieString(names.ACCESS_TOKEN, "", clearOptions),
  );
  resHeaders.append(
    "Set-Cookie",
    buildCookieString(names.REFRESH_TOKEN, "", clearOptions),
  );
  resHeaders.append(
    "Set-Cookie",
    buildCookieString(names.EXPIRES_AT, "", clearOptions),
  );
}
