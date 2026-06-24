"use client";

/**
 * Global app layout component.
 *
 * Applies Mantine AppShell + 60px top app bar to all (app) pages.
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

  // Show header bottom border on sidebar pages (workspace, account settings)
  const withBorder =
    pathname.startsWith("/w/") || pathname.startsWith("/account");

  return (
    <SidebarProvider>
      <AppShell header={{ height: 60 }} withBorder={withBorder}>
        <AppShell.Header>
          <AppBar authStatus={authStatus} />
        </AppShell.Header>
        <AppShell.Main>{children}</AppShell.Main>
      </AppShell>
    </SidebarProvider>
  );
}
