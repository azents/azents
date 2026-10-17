"use client";

import { Button, Menu } from "@mantine/core";
import { IconLanguage } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import {
  LOCALE_DISPLAY_NAMES,
  SUPPORTED_LOCALES,
  type SupportedLocale,
} from "@/shared/lib/locale";
import { useLocaleSwitcher } from "../containers/useLocaleSwitcher";
import type { LocaleSwitcherViewProps } from "../containers/useLocaleSwitcher";

export function LocaleSwitcher(): React.ReactElement {
  return <LocaleSwitcherView {...useLocaleSwitcher()} />;
}

export function LocaleSwitcherView({
  locale,
  onSelect,
}: LocaleSwitcherViewProps): React.ReactElement {
  const t = useTranslations("nav");

  return (
    <Menu shadow="md" width={160}>
      <Menu.Target>
        <Button
          aria-label={t("changeLanguage")}
          c="dimmed"
          leftSection={<IconLanguage size={16} />}
          radius="md"
          size="sm"
          variant="subtle"
        >
          {LOCALE_DISPLAY_NAMES[locale]}
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        {SUPPORTED_LOCALES.map((loc: SupportedLocale) => (
          <Menu.Item
            key={loc}
            onClick={() => onSelect(loc)}
            {...(loc !== locale && { c: "dimmed" })}
          >
            {LOCALE_DISPLAY_NAMES[loc]}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
