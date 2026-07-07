import { HomePage } from "@/features/home/HomePage";
import { getMessagesForLocale, resolveSupportedLocale } from "@/i18n/messages";
import {
  LOCALE_TO_OG_LOCALE,
  OG_IMAGE,
  SITE_NAME,
  SITE_URL,
} from "@/shared/lib/seo";
import type { Metadata } from "next";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale: localeParam } = await params;
  const locale = resolveSupportedLocale(localeParam);
  const messages = getMessagesForLocale(locale);
  const { title, description } = messages.metadata;

  return {
    alternates: {
      canonical: `/${locale}/`,
      languages: {
        "en-US": "/en-US/",
        "fr-FR": "/fr-FR/",
        "ja-JP": "/ja-JP/",
        "ko-KR": "/ko-KR/",
      },
    },
    description,
    openGraph: {
      description,
      images: [OG_IMAGE],
      locale: LOCALE_TO_OG_LOCALE[locale],
      siteName: SITE_NAME,
      title,
      type: "website",
      url: `${SITE_URL}/${locale}/`,
    },
    title,
    twitter: {
      card: "summary_large_image",
      description,
      images: [OG_IMAGE.url],
      title,
    },
  };
}

export default function Page(): React.ReactElement {
  return <HomePage />;
}
