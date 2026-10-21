"use client";

import { Authenticated, Refine } from "@refinedev/core";
import routerProvider from "@refinedev/nextjs-router";
import { usePathname } from "next/navigation";
import { Suspense, useMemo } from "react";
import { useConfig } from "@/config/client";
import { createAuthProvider } from "@/providers/auth-provider";
import { ColorModeProvider } from "@/providers/color-mode";
import { dataProvider } from "@/providers/data-provider";
import { TRPCProvider } from "@/providers/trpc";
import { AdminShellContainer } from "@/shared/AdminShellContainer";
import { ADMIN_RESOURCES } from "@/shared/lib/admin-navigation";
import { getPublicRoutePath } from "@/shared/lib/auth-policy";

type ColorModePreference = "light" | "dark" | "system";
type ColorMode = "light" | "dark";

function AppContent({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  const pathname = usePathname();
  const { publicBaseUrl } = useConfig();
  const loginPath = getPublicRoutePath(publicBaseUrl, "/login");
  const isLoginPage = pathname === loginPath || pathname === "/login";
  const authProvider = useMemo(
    () => createAuthProvider(publicBaseUrl),
    [publicBaseUrl],
  );
  const content = isLoginPage ? (
    children
  ) : (
    <AdminShellContainer>{children}</AdminShellContainer>
  );
  return (
    <Refine
      routerProvider={routerProvider}
      dataProvider={dataProvider}
      authProvider={authProvider}
      resources={ADMIN_RESOURCES.map((resource) => ({
        name: resource.name,
        list: getPublicRoutePath(publicBaseUrl, resource.list),
        meta: { icon: <resource.Icon size={20} />, label: resource.label },
      }))}
      options={{
        syncWithLocation: true,
        warnWhenUnsavedChanges: true,
        disableTelemetry: true,
      }}
    >
      {!isLoginPage ? (
        <Authenticated key="main">{content}</Authenticated>
      ) : (
        content
      )}
    </Refine>
  );
}

interface ClientLayoutProps {
  children: React.ReactNode;
  initialPreference: ColorModePreference;
  initialResolvedMode: ColorMode;
}

export function ClientLayout({
  children,
  initialPreference,
  initialResolvedMode,
}: ClientLayoutProps): React.ReactElement {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <TRPCProvider>
        <ColorModeProvider
          initialPreference={initialPreference}
          initialResolvedMode={initialResolvedMode}
        >
          <AppContent>{children}</AppContent>
        </ColorModeProvider>
      </TRPCProvider>
    </Suspense>
  );
}
