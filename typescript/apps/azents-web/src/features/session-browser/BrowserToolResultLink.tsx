"use client";

import { Button } from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  browserPanelHref,
  browserToolTarget,
  isBrowserSessionPath,
} from "./route";
import type { ReactElement } from "react";

export interface BrowserToolResultLinkProps {
  name: string;
  result: string | null;
}

export function BrowserToolResultLink({
  name,
  result,
}: BrowserToolResultLinkProps): ReactElement | null {
  const pathname = usePathname();
  const search = useSearchParams();
  const t = useTranslations("chat.browser");
  const target = browserToolTarget(name, result);
  if (target === null || !isBrowserSessionPath(pathname)) {
    return null;
  }
  return (
    <Button
      component={Link}
      href={browserPanelHref(pathname, search.toString(), target)}
      size="compact-xs"
      variant="subtle"
      mt="xs"
    >
      {t("open")}
    </Button>
  );
}
