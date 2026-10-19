"use client";

import { useTranslations } from "next-intl";
import { usePathname, useSearchParams } from "next/navigation";

export interface LoginRequiredViewProps {
  t: ReturnType<typeof useTranslations<"auth">>;
  loginUrl: string;
}

export function useLoginRequiredController(): LoginRequiredViewProps {
  const t = useTranslations("auth");
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const currentPath = searchParams.toString()
    ? `${pathname}?${searchParams.toString()}`
    : pathname;
  return {
    t,
    loginUrl: `/login?next=${encodeURIComponent(currentPath)}`,
  };
}
