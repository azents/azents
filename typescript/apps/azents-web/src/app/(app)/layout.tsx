import { ColorSchemeScript } from "@mantine/core";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import { cookies } from "next/headers";
import { TRPCProvider } from "@/app/providers";
import { AppLayout } from "@/shared/components/AppLayout";
import { AZENTS_BRAND } from "@/shared/lib/brand";
import {
  parseColorMode,
  parseColorModePreference,
} from "@/shared/lib/color-mode";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";
import { isSupportedLocale, type SupportedLocale } from "@/shared/lib/locale";
import { ColorModeProvider } from "@/shared/providers/color-mode";
import { LocaleProvider } from "@/shared/providers/locale";
import { AppMantineProvider } from "@/shared/providers/mantine";
import type { Metadata, Viewport } from "next";

import "@mantine/core/styles.css";
import "../globals.css";

/** Mobile Safari viewport settings (safe-area support) */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

/**
 * App page root layout.
 *
 * Reflects user color mode setting (cookie-based),
 * and supports realtime theme switching through ColorModeProvider.
 *
 * Color mode is isolated with separate root layout from (landing) route group.
 */

export async function generateMetadata(): Promise<Metadata> {
  const messages = await getMessages();
  const metadata = messages.metadata;
  return {
    title: metadata.title,
    description: metadata.description,
    icons: {
      icon: [
        { url: "/favicon.ico" },
        {
          url: "/brand/azents/favicon-32.png",
          sizes: "32x32",
          type: "image/png",
        },
        {
          url: "/brand/azents/favicon-16.png",
          sizes: "16x16",
          type: "image/png",
        },
      ],
      apple: [{ url: "/apple-icon.png", sizes: "180x180", type: "image/png" }],
    },
    openGraph: {
      title: metadata.title,
      description: metadata.description,
      images: [{ url: AZENTS_BRAND.openGraphImage, width: 1200, height: 630 }],
    },
    twitter: {
      card: "summary_large_image",
      title: metadata.title,
      description: metadata.description,
      images: [AZENTS_BRAND.openGraphImage],
    },
  };
}

export default async function RootAppLayout({
  children,
}: {
  children: React.ReactNode;
}): Promise<React.ReactElement> {
  // SSR: read locale (cookie → Accept-Language → default)
  const locale = await getLocale();
  const messages = await getMessages();
  const authState = await getInitialAuthState();

  const supportedLocale: SupportedLocale = isSupportedLocale(locale)
    ? locale
    : "en-US";

  // Extract language from BCP 47 locale (for HTML lang attribute)
  const htmlLang = supportedLocale.split("-")[0];

  // Read color mode cookie
  const cookieStore = await cookies();
  const preferenceCookie = cookieStore.get("color-mode-preference");
  const resolvedModeCookie = cookieStore.get("color-mode-resolved");

  const initialPreference = parseColorModePreference(
    preferenceCookie?.value ?? null,
  );
  const initialResolvedMode = parseColorMode(resolvedModeCookie?.value ?? null);

  // Use auto for system, otherwise use resolved mode
  const colorScheme =
    initialPreference === "system" ? "auto" : initialResolvedMode;

  return (
    <html lang={htmlLang} suppressHydrationWarning>
      <head>
        <ColorSchemeScript defaultColorScheme={colorScheme} />
      </head>
      <body className={`${GeistSans.variable} ${GeistMono.variable}`}>
        <NextIntlClientProvider messages={messages}>
          <AppMantineProvider defaultColorScheme={colorScheme}>
            <TRPCProvider>
              <LocaleProvider locale={supportedLocale}>
                <ColorModeProvider
                  initialPreference={initialPreference}
                  initialResolvedMode={initialResolvedMode}
                >
                  <AppLayout authStatus={authState.status}>
                    {children}
                  </AppLayout>
                </ColorModeProvider>
              </LocaleProvider>
            </TRPCProvider>
          </AppMantineProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
