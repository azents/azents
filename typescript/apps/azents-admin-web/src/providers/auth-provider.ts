"use client";

import { z } from "zod/v4";
import {
  getNativeLoginUrl,
  getNativePostLoginUrl,
  getNativePublicRouteUrl,
  getPublicRoutePath,
  getPublicRouteUrl,
  isPublicRouteUrl,
} from "../shared/lib/auth-policy.ts";
import type { AuthProvider } from "@refinedev/core";

const LoginInputSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

const SessionSchema = z.object({
  user_id: z.string(),
});

async function readErrorMessage(response: Response): Promise<string> {
  const body: unknown = await response.json();
  if (
    typeof body === "object" &&
    body !== null &&
    "error" in body &&
    typeof body.error === "string"
  ) {
    return body.error;
  }
  return "Admin authentication failed.";
}

export function createAuthProvider(publicBaseUrl: string): AuthProvider {
  const sessionUrl = getPublicRouteUrl(publicBaseUrl, "/api/session");
  const homePath = getPublicRoutePath(publicBaseUrl, "/workspaces");
  const loginPath = getPublicRoutePath(publicBaseUrl, "/login");

  const navigateAfterAuth = (
    path: string,
    nativeUrl: string | null,
  ): string | null => {
    if (!nativeUrl) {
      return path;
    }
    window.location.replace(nativeUrl);
    return null;
  };

  return {
    login: async (input) => {
      const parsedInput = LoginInputSchema.safeParse(input);
      if (!parsedInput.success) {
        return {
          success: false,
          error: {
            name: "InvalidCredentials",
            message: "A valid email and password are required.",
          },
        };
      }

      const response = await fetch(sessionUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsedInput.data),
      });
      if (!response.ok) {
        return {
          success: false,
          error: {
            name: response.status === 403 ? "Forbidden" : "LoginFailed",
            message: await readErrorMessage(response),
          },
        };
      }
      const redirectTo = navigateAfterAuth(
        homePath,
        getNativePostLoginUrl(publicBaseUrl, window.location.href),
      );
      return redirectTo ? { success: true, redirectTo } : { success: true };
    },
    logout: async () => {
      const response = await fetch(sessionUrl, {
        method: "DELETE",
        credentials: "same-origin",
      });
      if (!response.ok) {
        return {
          success: false,
          error: {
            name: "LogoutFailed",
            message: await readErrorMessage(response),
          },
        };
      }
      const redirectTo = navigateAfterAuth(
        loginPath,
        getNativePublicRouteUrl(publicBaseUrl, "/login"),
      );
      return redirectTo ? { success: true, redirectTo } : { success: true };
    },
    check: async () => {
      const response = await fetch(sessionUrl, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      });
      if (response.ok) {
        return { authenticated: true };
      }
      if (isPublicRouteUrl(publicBaseUrl, window.location.href, "/login")) {
        return { authenticated: false, logout: true };
      }
      const redirectTo = navigateAfterAuth(
        loginPath,
        getNativeLoginUrl(publicBaseUrl, window.location.href),
      );
      return redirectTo
        ? { authenticated: false, redirectTo, logout: true }
        : { authenticated: false, logout: true };
    },
    getPermissions: () => Promise.resolve(["system_admin"]),
    getIdentity: async () => {
      const response = await fetch(sessionUrl, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) {
        return null;
      }
      const session = SessionSchema.parse(await response.json());
      return {
        id: session.user_id,
        name: "System administrator",
        avatar: "",
      };
    },
    onError: (error: Error) => Promise.resolve({ error }),
  };
}
