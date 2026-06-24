"use client";

import { getSession, signIn, signOut } from "next-auth/react";
import type { AuthProvider } from "@refinedev/core";

export const authProvider: AuthProvider = {
  login: async () => {
    await signIn("github", { callbackUrl: "/" });
    return { success: true };
  },
  logout: async () => {
    await signOut({ callbackUrl: "/login" });
    return { success: true };
  },
  check: async () => {
    const session = await getSession();
    if (session) {
      return { authenticated: true };
    }
    return { authenticated: false, redirectTo: "/login" };
  },
  getPermissions: () => Promise.resolve(null),
  getIdentity: async () => {
    const session = await getSession();
    if (session?.user) {
      return {
        id: session.user.email,
        name: session.user.name,
        avatar: session.user.image,
      };
    }
    return null;
  },
  onError: (error: Error) => {
    console.error(error);
    return Promise.resolve({ error });
  },
};
