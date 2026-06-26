"use client";

/**
 * Global app layout component.
 *
 * Applies Mantine AppShell and hides the global top app bar on Agent-focused pages.
 */
import { AppShell } from "@mantine/core";
import { usePathname } from "next/navigation";
import { AppBar } from "@/shared/components/AppBar";
import { SidebarProvider } from "@/shared/providers/sidebar";
import type { ReactNode } from "react";

interface AppLayoutProps {
  authStatus: "authenticated" | "unauthenticated";
  children: ReactNode;
}

export function AppLayout({
  authStatus,
  children,
}: AppLayoutProps): React.ReactElement {
  const pathname = usePathname();
  const isAgentDetailRoute = /^\/w\/[^/]+\/agents\/(?!new(?:\/|$))[^/]+/.test(
    pathname,
  );
  const headerHeight = isAgentDetailRoute ? 0 : 60;

  // Show header bottom border on sidebar pages (workspace, account settings)
  const withBorder =
    (pathname.startsWith("/w/") && !isAgentDetailRoute) ||
    pathname.startsWith("/account");

  return (
    <SidebarProvider>
      <AppShell header={{ height: headerHeight }} withBorder={withBorder}>
        {!isAgentDetailRoute && (
          <AppShell.Header>
            <AppBar authStatus={authStatus} />
          </AppShell.Header>
        )}
        <AppShell.Main>{children}</AppShell.Main>
      </AppShell>
    </SidebarProvider>
  );
}
