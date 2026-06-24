import { ColorSchemeScript } from "@mantine/core";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import { AZENTS_BRAND } from "@/shared/lib/brand";
import { isSupportedLocale, type SupportedLocale } from "@/shared/lib/locale";
import { LocaleProvider } from "@/shared/providers/locale";
import { AppMantineProvider } from "@/shared/providers/mantine";
import type { Metadata } from "next";

import "@mantine/core/styles.css";
import "../globals.css";

/**
 * Root layout dedicated to landing page.
 *
 * Sets forceColorScheme="dark" on both ColorSchemeScript and MantineProvider to
 * ensure data-mantine-color-scheme="dark" on html element and body background
 * for complete dark mode.
 *
 * Color mode is isolated with separate root layout from (app) route group.
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

export default async function LandingLayout({
  children,
}: {
  children: React.ReactNode;
}): Promise<React.ReactElement> {
  const locale = await getLocale();
  const messages = await getMessages();

  const supportedLocale: SupportedLocale = isSupportedLocale(locale)
    ? locale
    : "en-US";

  const htmlLang = supportedLocale.split("-")[0];

  return (
    <html lang={htmlLang} suppressHydrationWarning>
      <head>
        <ColorSchemeScript forceColorScheme="dark" />
      </head>
      <body className={`${GeistSans.variable} ${GeistMono.variable}`}>
        <NextIntlClientProvider messages={messages}>
          <AppMantineProvider forceColorScheme="dark">
            <LocaleProvider locale={supportedLocale}>{children}</LocaleProvider>
          </AppMantineProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
