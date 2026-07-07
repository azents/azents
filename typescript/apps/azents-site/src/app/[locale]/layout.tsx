import { NextIntlClientProvider } from "next-intl";
import { getMessagesForLocale, resolveSupportedLocale } from "@/i18n/messages";
import { SUPPORTED_LOCALES, type SupportedLocale } from "@/shared/lib/locale";
import { LocaleProvider } from "@/shared/providers/locale";
import type { ReactNode } from "react";

export function generateStaticParams(): Array<{ locale: SupportedLocale }> {
  return SUPPORTED_LOCALES.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}): Promise<React.ReactElement> {
  const { locale: localeParam } = await params;
  const locale = resolveSupportedLocale(localeParam);
  const messages = getMessagesForLocale(locale);

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      <LocaleProvider locale={locale}>{children}</LocaleProvider>
    </NextIntlClientProvider>
  );
}
