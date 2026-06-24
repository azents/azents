/**
 * Login route
 *
 * Already authenticated user is immediately redirected to next parameter path (replace).
 *
 * When cookies remain but token is actually invalid (e.g. refresh token expired),
 * redirecting to auth-required path such as `next=/w/...` causes that path to
 * redirect back to `/login`, causing infinite loop. Server Component cannot write cookies,
 * so cookies cannot be cleared even after UNAUTHORIZED. To prevent this, just before redirect,
 * verify actual token validity and render LoginPage without redirect if invalid.
 */
import { TRPCError } from "@trpc/server";
import { redirect, RedirectType } from "next/navigation";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";
import { trpc } from "@/trpc/server";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Partial<Record<string, string | string[]>>>;
}): Promise<React.ReactElement> {
  const authState = await getInitialAuthState();

  if (authState.status === "authenticated") {
    // Cookie-existence decision and actual token validity can differ, so verify once.
    let sessionValid = true;
    try {
      await trpc.user.me();
    } catch (e) {
      if (e instanceof TRPCError && e.code === "UNAUTHORIZED") {
        sessionValid = false;
      } else {
        throw e;
      }
    }

    if (sessionValid) {
      const params = await searchParams;
      const next =
        typeof params.next === "string" &&
        params.next.startsWith("/") &&
        !params.next.startsWith("//")
          ? params.next
          : "/workspaces";
      redirect(next, RedirectType.replace);
    }
  }

  return <LoginPage />;
}
