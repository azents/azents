import { ColorSchemeScript } from "@mantine/core";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import { cookies } from "next/headers";
import { AZENTS_BRAND } from "@/shared/lib/brand";
import {
  parseColorMode,
  parseColorModePreference,
} from "@/shared/lib/color-mode";
import { isSupportedLocale, type SupportedLocale } from "@/shared/lib/locale";
import { ColorModeProvider } from "@/shared/providers/color-mode";
import { LocaleProvider } from "@/shared/providers/locale";
import { AppMantineProvider } from "@/shared/providers/mantine";
import type { Metadata } from "next";

import "@mantine/core/styles.css";
import "../globals.css";

/** Landing page metadata localized through next-intl. */
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

export default async function LandingLayout({
  children,
}: {
  children: React.ReactNode;
}): Promise<React.ReactElement> {
  const locale = await getLocale();
  const messages = await getMessages();
  const cookieStore = await cookies();

  const supportedLocale: SupportedLocale = isSupportedLocale(locale)
    ? locale
    : "en-US";
  const htmlLang = supportedLocale.split("-")[0];

  const preferenceCookie = cookieStore.get("color-mode-preference");
  const resolvedModeCookie = cookieStore.get("color-mode-resolved");
  const initialPreference = preferenceCookie
    ? parseColorModePreference(preferenceCookie.value)
    : "dark";
  const initialResolvedMode = resolvedModeCookie
    ? parseColorMode(resolvedModeCookie.value)
    : initialPreference === "light"
      ? "light"
      : "dark";
  const colorScheme =
    initialPreference === "system" ? "auto" : initialResolvedMode;

  return (
    <html
      lang={htmlLang}
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <ColorSchemeScript defaultColorScheme={colorScheme} />
      </head>
      <body className={GeistSans.className}>
        <NextIntlClientProvider messages={messages}>
          <AppMantineProvider defaultColorScheme={colorScheme}>
            <LocaleProvider locale={supportedLocale}>
              <ColorModeProvider
                initialPreference={initialPreference}
                initialResolvedMode={initialResolvedMode}
              >
                {children}
              </ColorModeProvider>
            </LocaleProvider>
          </AppMantineProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
