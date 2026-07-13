"use client";

import { z } from "zod/v4";
import {
  getPublicRoutePath,
  getPublicRouteUrl,
} from "@/shared/lib/auth-policy";
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
  const homePath = getPublicRoutePath(publicBaseUrl, "/");
  const loginPath = getPublicRoutePath(publicBaseUrl, "/login");

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
      return { success: true, redirectTo: homePath };
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
      return { success: true, redirectTo: loginPath };
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
      return { authenticated: false, redirectTo: loginPath, logout: true };
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
