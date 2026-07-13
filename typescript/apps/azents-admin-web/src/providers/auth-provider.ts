"use client";

import { z } from "zod/v4";
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

export const authProvider: AuthProvider = {
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

    const response = await fetch("/api/session", {
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
    return { success: true, redirectTo: "/" };
  },
  logout: async () => {
    const response = await fetch("/api/session", {
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
    return { success: true, redirectTo: "/login" };
  },
  check: async () => {
    const response = await fetch("/api/session", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    });
    if (response.ok) {
      return { authenticated: true };
    }
    return { authenticated: false, redirectTo: "/login", logout: true };
  },
  getPermissions: () => Promise.resolve(["system_admin"]),
  getIdentity: async () => {
    const response = await fetch("/api/session", {
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
