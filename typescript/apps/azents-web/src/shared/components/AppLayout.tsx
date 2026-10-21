"use client";
/**
 * Global app layout component.
 *
 * Applies Mantine AppShell and hides the global top app bar on Agent-focused pages.
 */
import { AppShell } from "@mantine/core";

import { AppBar } from "@/shared/components/AppBar";
import { ScrollContainedViewport } from "@/shared/components/ScrollContainedViewport";
import { AccountLocaleSync } from "@/shared/providers/account-locale-sync";
import { SidebarProvider } from "@/shared/providers/sidebar";
import { useAppLayoutController } from "../containers/useAppLayoutController";
import type { AppLayoutViewProps } from "../containers/useAppLayoutController";
import type { ReactNode } from "react";

interface AppLayoutProps {
  authStatus: "authenticated" | "unauthenticated";
  children: ReactNode;
}

export function AppLayout(props: AppLayoutProps): React.ReactElement {
  return <AppLayoutView {...useAppLayoutController(props)} />;
}

export function AppLayoutView({
  authStatus,
  children,
  isAgentDetailRoute,
  isChatRoute,
  headerHeight,
  withBorder,
}: AppLayoutViewProps): React.ReactElement {
  return (
    <SidebarProvider>
      <AccountLocaleSync authStatus={authStatus} />
      <AppShell header={{ height: headerHeight }} withBorder={withBorder}>
        {!isAgentDetailRoute && (
          <AppShell.Header>
            <AppBar authStatus={authStatus} />
          </AppShell.Header>
        )}
        <AppShell.Main>
          {isChatRoute ? (
            <ScrollContainedViewport>{children}</ScrollContainedViewport>
          ) : (
            children
          )}
        </AppShell.Main>
      </AppShell>
    </SidebarProvider>
  );
}
