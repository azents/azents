"use client";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import {
  DEFAULT_LOCALE,
  isSupportedLocale,
  type SupportedLocale,
} from "@/shared/lib/locale";
interface AccountLocaleFormProps {
  locale: string;
  localeUpdate: {
    isPending: boolean;
    hasError: boolean;
  };
  onSubmit: (locale: SupportedLocale) => void;
}

export interface AccountLocaleFormViewProps {
  localeUpdate: AccountLocaleFormProps["localeUpdate"];
  onSubmit: AccountLocaleFormProps["onSubmit"];
  t: ReturnType<typeof useTranslations<"account">>;
  locale: "en-US" | "ko-KR" | "ja-JP" | "fr-FR";
  setLocale: React.Dispatch<
    React.SetStateAction<"en-US" | "ko-KR" | "ja-JP" | "fr-FR">
  >;
}
export function useAccountLocaleFormController({
  locale: initialLocale,
  localeUpdate,
  onSubmit,
}: AccountLocaleFormProps): AccountLocaleFormViewProps {
  const t = useTranslations("account");
  const [locale, setLocale] = useState<SupportedLocale>(
    isSupportedLocale(initialLocale) ? initialLocale : DEFAULT_LOCALE,
  );

  useEffect(() => {
    if (isSupportedLocale(initialLocale)) {
      setLocale(initialLocale);
    }
  }, [initialLocale]);
  return { localeUpdate, onSubmit, t, locale, setLocale };
}
