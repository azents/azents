import { ColorSchemeScript, MantineProvider } from "@mantine/core";
import { ModalsProvider } from "@mantine/modals";
import { Notifications } from "@mantine/notifications";
import { cookies } from "next/headers";
import { getPublicConfig } from "@/config";
import { ConfigProvider } from "@/config/client";
import { SessionProvider } from "@/providers/session";
import { ClientLayout } from "./client-layout";

import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";

export const metadata = {
  title: "Azents Admin",
  description: "Admin panel for Azents",
};

type ColorModePreference = "light" | "dark" | "system";
type ColorMode = "light" | "dark";

function parseColorModePreference(value: string | null): ColorModePreference {
  if (value === "light" || value === "dark" || value === "system") {
    return value;
  }
  return "system";
}

function parseColorMode(value: string | null): ColorMode {
  if (value === "light" || value === "dark") {
    return value;
  }
  return "light";
}

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}): Promise<React.ReactElement> {
  const cookieStore = await cookies();
  const preferenceCookie = cookieStore.get("color-mode-preference");
  const resolvedModeCookie = cookieStore.get("color-mode-resolved");

  const initialPreference = parseColorModePreference(
    preferenceCookie?.value ?? null,
  );
  const initialResolvedMode = parseColorMode(resolvedModeCookie?.value ?? null);

  // Use 'auto' if preference is 'system', otherwise use the resolved mode
  const colorScheme =
    initialPreference === "system" ? "auto" : initialResolvedMode;

  return (
    <html lang="ko" style={{ height: "100%" }} suppressHydrationWarning>
      <head>
        <ColorSchemeScript defaultColorScheme={colorScheme} />
      </head>
      <body style={{ height: "100%", margin: 0 }}>
        <ConfigProvider config={getPublicConfig()}>
          <MantineProvider defaultColorScheme={colorScheme}>
            <ModalsProvider>
              <Notifications position="top-right" />
              <SessionProvider>
                <ClientLayout
                  initialPreference={initialPreference}
                  initialResolvedMode={initialResolvedMode}
                >
                  {children}
                </ClientLayout>
              </SessionProvider>
            </ModalsProvider>
          </MantineProvider>
        </ConfigProvider>
      </body>
    </html>
  );
}
