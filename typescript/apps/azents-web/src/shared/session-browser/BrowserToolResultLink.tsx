"use client";

import { Button } from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useBrowserToolResultLink } from "./useBrowserToolResultLink";
import type { ReactElement } from "react";

export function BrowserToolResultLinkView({
  href,
}: {
  href: string | null;
}): ReactElement | null {
  const t = useTranslations("chat.browser");
  if (href === null) {
    return null;
  }
  return (
    <Button
      component={Link}
      href={href}
      size="compact-xs"
      variant="subtle"
      mt="xs"
    >
      {t("open")}
    </Button>
  );
}

export const BrowserToolResultLink = createReactContainer(
  "BrowserToolResultLink",
  useBrowserToolResultLink,
  BrowserToolResultLinkView,
);
