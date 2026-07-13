import "server-only";
import { cookies } from "next/headers";
import { getPublicConfig } from "@/config";
import { getServerConfig } from "@/config/server";
import { getAuthCookiePath } from "./auth-policy";

export const ADMIN_AUTH_COOKIE_NAMES = {
  ACCESS_TOKEN: "az-admin-token",
  REFRESH_TOKEN: "az-admin-refresh",
  EXPIRES_AT: "az-admin-token-expires-at",
};

export interface StoredAccessToken {
  token: string;
  expiresAt: number;
}

export interface AdminAuthTokens {
  accessToken: string;
  refreshToken: string;
  expiresInSeconds: number;
}

export async function getAdminAccessToken(): Promise<StoredAccessToken | null> {
  const cookieStore = await cookies();
  const token = cookieStore.get(ADMIN_AUTH_COOKIE_NAMES.ACCESS_TOKEN)?.value;
  const expiresAtValue = cookieStore.get(
    ADMIN_AUTH_COOKIE_NAMES.EXPIRES_AT,
  )?.value;

  if (!token || !expiresAtValue) {
    return null;
  }

  const expiresAt = Number(expiresAtValue);
  if (Number.isNaN(expiresAt)) {
    return null;
  }
  return { token, expiresAt };
}

export async function getAdminRefreshToken(): Promise<string | null> {
  const cookieStore = await cookies();
  return cookieStore.get(ADMIN_AUTH_COOKIE_NAMES.REFRESH_TOKEN)?.value ?? null;
}

export function isAdminAccessTokenExpiringSoon(expiresAt: number): boolean {
  const refreshThresholdMs = 5 * 60 * 1000;
  return Date.now() + refreshThresholdMs >= expiresAt;
}

interface CookieOptions {
  httpOnly: boolean;
  secure: boolean;
  sameSite: "lax";
  path: string;
  maxAge?: number;
}

function buildCookieString(
  name: string,
  value: string,
  options: CookieOptions,
): string {
  const parts = [
    `${name}=${value}`,
    `Path=${options.path}`,
    `SameSite=${options.sameSite.charAt(0).toUpperCase()}${options.sameSite.slice(1)}`,
  ];
  if (options.maxAge != null) {
    parts.push(`Max-Age=${options.maxAge}`);
  }
  if (options.httpOnly) {
    parts.push("HttpOnly");
  }
  if (options.secure) {
    parts.push("Secure");
  }
  return parts.join("; ");
}

export function setAdminAuthCookies(
  responseHeaders: Headers,
  tokens: AdminAuthTokens,
): void {
  const commonOptions: CookieOptions = {
    httpOnly: true,
    secure: getServerConfig().nodeEnv === "production",
    sameSite: "lax",
    path: getAuthCookiePath(getPublicConfig().publicBaseUrl),
  };
  const expiresAt = Date.now() + tokens.expiresInSeconds * 1000;

  responseHeaders.append(
    "Set-Cookie",
    buildCookieString(
      ADMIN_AUTH_COOKIE_NAMES.ACCESS_TOKEN,
      tokens.accessToken,
      commonOptions,
    ),
  );
  responseHeaders.append(
    "Set-Cookie",
    buildCookieString(
      ADMIN_AUTH_COOKIE_NAMES.REFRESH_TOKEN,
      tokens.refreshToken,
      {
        ...commonOptions,
        maxAge: 30 * 24 * 60 * 60,
      },
    ),
  );
  responseHeaders.append(
    "Set-Cookie",
    buildCookieString(
      ADMIN_AUTH_COOKIE_NAMES.EXPIRES_AT,
      String(expiresAt),
      commonOptions,
    ),
  );
}

export function clearAdminAuthCookies(responseHeaders: Headers): void {
  const options: CookieOptions = {
    httpOnly: true,
    secure: getServerConfig().nodeEnv === "production",
    sameSite: "lax",
    path: getAuthCookiePath(getPublicConfig().publicBaseUrl),
    maxAge: 0,
  };

  for (const name of Object.values(ADMIN_AUTH_COOKIE_NAMES)) {
    responseHeaders.append("Set-Cookie", buildCookieString(name, "", options));
  }
}
