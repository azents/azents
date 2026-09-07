"use client";

/** Locale switch menu component */
import { Button, Menu } from "@mantine/core";
import { IconLanguage } from "@tabler/icons-react";
import {
  LOCALE_DISPLAY_NAMES,
  SUPPORTED_LOCALES,
  type SupportedLocale,
} from "@/shared/lib/locale";
import { useLocale } from "@/shared/providers/locale";

export function LocaleSwitcher(): React.ReactElement {
  const { locale, setLocale } = useLocale();

  return (
    <Menu shadow="md" width={160} id="locale-switcher-menu">
      <Menu.Target>
        <Button
          variant="subtle"
          size="compact-sm"
          c="dimmed"
          leftSection={<IconLanguage size={16} />}
        >
          {LOCALE_DISPLAY_NAMES[locale]}
        </Button>
      </Menu.Target>

      <Menu.Dropdown>
        {SUPPORTED_LOCALES.map((loc: SupportedLocale) => (
          <Menu.Item
            key={loc}
            onClick={() => setLocale(loc)}
            {...(loc !== locale && { c: "dimmed" })}
          >
            {LOCALE_DISPLAY_NAMES[loc]}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
