/**
 * Server-side initial authentication state check.
 *
 * Determines authentication state by cookie existence.
 * - authenticated when access token exists
 * - authenticated when refresh token exists even without access token
 *   (interceptor refreshes access token automatically on first API call)
 * - unauthenticated when neither exists
 *
 * Runs only once within the same request through React cache().
 */
import "server-only";
import { cookies } from "next/headers";
import { cache } from "react";
import { COOKIE_NAMES } from "@/shared/lib/cookies";

export type InitialAuthState =
  | { status: "authenticated" }
  | { status: "unauthenticated" };

/**
 * Fetch authentication state (cached).
 *
 * Even when called multiple times within the same request, it runs only once.
 */
export const getInitialAuthState = cache(
  async (): Promise<InitialAuthState> => {
    const cookieStore = await cookies();
    const accessToken = cookieStore.get(COOKIE_NAMES.ACCESS_TOKEN)?.value;
    const refreshToken = cookieStore.get(COOKIE_NAMES.REFRESH_TOKEN)?.value;

    // Treat as authenticated when access token or refresh token exists
    // (when only refresh token exists, interceptor refreshes access token automatically)
    if (accessToken || refreshToken) {
      return { status: "authenticated" };
    }

    return { status: "unauthenticated" };
  },
);
