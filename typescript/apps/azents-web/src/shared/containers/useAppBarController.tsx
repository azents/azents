"use client";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useCallback } from "react";
import { useSidebar } from "@/shared/providers/sidebar";
import { trpc } from "@/trpc/client";
interface AppBarProps {
  authStatus: "authenticated" | "unauthenticated";
}
function extractWorkspaceHandle(pathname: string): string | null {
  const match = pathname.match(/^\/w\/([^/]+)/);
  return match?.[1] ?? null;
}
export interface AppBarViewProps {
  t: ReturnType<typeof useTranslations<"appBar">>;
  sidebarOpened: boolean;
  toggleSidebar: () => void;
  isAuthenticated: boolean;
  adminAccess?: { url: string | null };
  adminAccessPending: boolean;
  workspaceHandle: string | null;
  hasSidebar: boolean;
  logoutMutation: ReturnType<typeof trpc.auth.logout.useMutation>;
  onLogout: () => void;
  onAccount: () => void;
  logoHref: "/workspaces" | "/";
}
export function useAppBarController({
  authStatus,
}: AppBarProps): AppBarViewProps {
  const t = useTranslations("appBar");
  const router = useRouter();
  const pathname = usePathname();
  const { opened: sidebarOpened, toggle: toggleSidebar } = useSidebar();
  const isAuthenticated = authStatus === "authenticated";
  const { data: adminAccess, isPending: adminAccessPending } =
    trpc.user.adminAccess.useQuery(
      {},
      {
        enabled: isAuthenticated,
        retry: false,
      },
    );
  const workspaceHandle = extractWorkspaceHandle(pathname);
  const isAgentDetailRoute = /^\/w\/[^/]+\/agents\/(?!new(?:\/|$))[^/]+/.test(
    pathname,
  );
  /** Whether page has workspace/account sidebar */
  const hasSidebar =
    (workspaceHandle !== null && !isAgentDetailRoute) ||
    pathname.startsWith("/account");

  const logoutMutation = trpc.auth.logout.useMutation({
    onSuccess: () => {
      router.push("/");
    },
  });

  const onLogout = useCallback((): void => {
    logoutMutation.mutate();
  }, [logoutMutation]);

  const onAccount = useCallback((): void => {
    router.push("/account");
  }, [router]);

  const logoHref = isAuthenticated ? "/workspaces" : "/";
  return {
    t,
    sidebarOpened,
    toggleSidebar,
    isAuthenticated,
    adminAccess,
    adminAccessPending,
    workspaceHandle,
    hasSidebar,
    logoutMutation,
    onLogout,
    onAccount,
    logoHref,
  };
}
