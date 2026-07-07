import { ColorSchemeScript } from "@mantine/core";
import { NextIntlClientProvider } from "next-intl";
import { getPublicConfig } from "@/config";
import { getMessagesForLocale } from "@/i18n/messages";
import { GoogleAnalytics } from "@/shared/components/GoogleAnalytics";
import { AZENTS_BRAND } from "@/shared/lib/brand";
import { DEFAULT_LOCALE } from "@/shared/lib/locale";
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

export function generateMetadata(): Metadata {
  const messages = getMessagesForLocale(DEFAULT_LOCALE);
  const { title, description } = messages.metadata;

  return {
    metadataBase: new URL(SITE_URL),
    alternates: {
      canonical: "/",
      languages: {
        "en-US": "/en-US/",
        "fr-FR": "/fr-FR/",
        "ja-JP": "/ja-JP/",
        "ko-KR": "/ko-KR/",
      },
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
      locale: LOCALE_TO_OG_LOCALE[DEFAULT_LOCALE],
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

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}): React.ReactElement {
  const messages = getMessagesForLocale(DEFAULT_LOCALE);
  const { siteGoogleAnalyticsId } = getPublicConfig();

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <ColorSchemeScript forceColorScheme="dark" />
        <script
          dangerouslySetInnerHTML={{ __html: JSON.stringify(STRUCTURED_DATA) }}
          type="application/ld+json"
        />
      </head>
      <body>
        {siteGoogleAnalyticsId ? (
          <GoogleAnalytics measurementId={siteGoogleAnalyticsId} />
        ) : null}
        <NextIntlClientProvider locale={DEFAULT_LOCALE} messages={messages}>
          <AppMantineProvider forceColorScheme="dark">
            <LocaleProvider locale={DEFAULT_LOCALE}>{children}</LocaleProvider>
          </AppMantineProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
