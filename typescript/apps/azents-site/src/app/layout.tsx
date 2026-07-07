import { ColorSchemeScript } from "@mantine/core";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";
import { unstable_noStore as noStore } from "next/cache";
import { getPublicConfig } from "@/config";
import { GoogleAnalytics } from "@/shared/components/GoogleAnalytics";
import { AZENTS_BRAND } from "@/shared/lib/brand";
import {
  DEFAULT_LOCALE,
  isSupportedLocale,
  type SupportedLocale,
} from "@/shared/lib/locale";
import {
  LOCALE_TO_OG_LOCALE,
  OG_IMAGE,
  SEO_KEYWORDS,
  SITE_NAME,
  SITE_URL,
  STRUCTURED_DATA,
} from "@/shared/lib/seo";
import { LocaleProvider } from "@/shared/providers/locale";
import { AppMantineProvider } from "@/shared/providers/mantine";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@fontsource-variable/inter";
import "@mantine/core/styles.css";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getLocale();
  const supportedLocale: SupportedLocale = isSupportedLocale(locale)
    ? locale
    : DEFAULT_LOCALE;
  const t = await getTranslations("metadata");
  const title = t("title");
  const description = t("description");

  return {
    metadataBase: new URL(SITE_URL),
    alternates: {
      canonical: "/",
    },
    applicationName: SITE_NAME,
    authors: [{ name: "Azents", url: SITE_URL }],
    category: "developer tools",
    creator: "Azents",
    description,
    icons: {
      apple: [{ url: AZENTS_BRAND.icon, sizes: "180x180" }],
      icon: [
        { url: "/brand/azents/favicon-32.png", sizes: "32x32" },
        { url: "/brand/azents/favicon-16.png", sizes: "16x16" },
      ],
    },
    keywords: SEO_KEYWORDS,
    manifest: "/manifest.webmanifest",
    openGraph: {
      description,
      images: [OG_IMAGE],
      locale: LOCALE_TO_OG_LOCALE[supportedLocale],
      siteName: SITE_NAME,
      title,
      type: "website",
      url: SITE_URL,
    },
    publisher: "Azents",
    robots: {
      follow: true,
      googleBot: {
        follow: true,
        index: true,
        "max-image-preview": "large",
        "max-snippet": -1,
        "max-video-preview": -1,
      },
      index: true,
    },
    title,
    twitter: {
      card: "summary_large_image",
      description,
      images: [AZENTS_BRAND.openGraphImage],
      title,
    },
  };
}

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}): Promise<React.ReactElement> {
  noStore();

  const locale = await getLocale();
  const messages = await getMessages();
  const { googleAnalyticsId } = getPublicConfig();

  const supportedLocale: SupportedLocale = isSupportedLocale(locale)
    ? locale
    : DEFAULT_LOCALE;
  const htmlLang = supportedLocale.split("-")[0];

  return (
    <html lang={htmlLang} suppressHydrationWarning>
      <head>
        <ColorSchemeScript forceColorScheme="dark" />
        <script
          dangerouslySetInnerHTML={{ __html: JSON.stringify(STRUCTURED_DATA) }}
          type="application/ld+json"
        />
      </head>
      <body>
        {googleAnalyticsId ? (
          <GoogleAnalytics measurementId={googleAnalyticsId} />
        ) : null}
        <NextIntlClientProvider messages={messages}>
          <AppMantineProvider forceColorScheme="dark">
            <LocaleProvider locale={supportedLocale}>{children}</LocaleProvider>
          </AppMantineProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
