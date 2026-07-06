import { ColorSchemeScript } from "@mantine/core";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";
import { AZENTS_BRAND } from "@/shared/lib/brand";
import { SITE_LINKS } from "@/shared/lib/links";
import {
  DEFAULT_LOCALE,
  isSupportedLocale,
  type SupportedLocale,
} from "@/shared/lib/locale";
import { LocaleProvider } from "@/shared/providers/locale";
import { AppMantineProvider } from "@/shared/providers/mantine";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@mantine/core/styles.css";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("metadata");

  return {
    title: t("title"),
    description: t("description"),
    icons: {
      icon: [
        { url: "/brand/azents/favicon-32.png", sizes: "32x32" },
        { url: "/brand/azents/favicon-16.png", sizes: "16x16" },
      ],
    },
    openGraph: {
      title: t("title"),
      description: t("description"),
      images: [{ url: AZENTS_BRAND.openGraphImage, width: 1200, height: 630 }],
      type: "website",
      url: SITE_LINKS.github,
    },
    twitter: {
      card: "summary_large_image",
      title: t("title"),
      description: t("description"),
      images: [AZENTS_BRAND.openGraphImage],
    },
  };
}

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}): Promise<React.ReactElement> {
  const locale = await getLocale();
  const messages = await getMessages();

  const supportedLocale: SupportedLocale = isSupportedLocale(locale)
    ? locale
    : DEFAULT_LOCALE;
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
