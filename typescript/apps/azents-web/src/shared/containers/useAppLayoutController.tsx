"use client";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
interface AppLayoutProps {
  authStatus: "authenticated" | "unauthenticated";
  children: ReactNode;
}

export interface AppLayoutViewProps {
  authStatus: AppLayoutProps["authStatus"];
  children: AppLayoutProps["children"];
  isAgentDetailRoute: boolean;
  headerHeight: 0 | 60;
  withBorder: boolean;
}
export function useAppLayoutController({
  authStatus,
  children,
}: AppLayoutProps): AppLayoutViewProps {
  const pathname = usePathname();
  const isAgentDetailRoute = /^\/w\/[^/]+\/agents\/(?!new(?:\/|$))[^/]+/.test(
    pathname,
  );
  const headerHeight = isAgentDetailRoute ? 0 : 60;

  // Show header bottom border on sidebar pages (workspace, account settings)
  const withBorder =
    (pathname.startsWith("/w/") && !isAgentDetailRoute) ||
    pathname.startsWith("/account");
  return { authStatus, children, isAgentDetailRoute, headerHeight, withBorder };
}
