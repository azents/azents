"use client";

/**
 * Color mode switch component.
 *
 * Icon button for selecting light / dark / system modes from menu.
 */
import { ActionIcon, Menu } from "@mantine/core";
import { useMantineColorScheme } from "@mantine/core";
import {
  IconBrightnessAuto,
  IconCheck,
  IconMoon,
  IconSun,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useColorMode } from "@/shared/providers/color-mode";
import type { ColorModePreference } from "@/shared/lib/color-mode";

export function ColorModeSwitcher(): React.ReactElement {
  const { mode, preference, setColorMode } = useColorMode();
  const { setColorScheme } = useMantineColorScheme();
  const t = useTranslations("common");

  function handleSelect(newPreference: ColorModePreference): void {
    setColorMode(newPreference);
    if (newPreference === "system") {
      setColorScheme("auto");
    } else {
      setColorScheme(newPreference);
    }
  }

  function getCurrentIcon(): React.ReactElement {
    if (preference === "system") {
      return <IconBrightnessAuto size={20} />;
    }
    return mode === "dark" ? <IconMoon size={20} /> : <IconSun size={20} />;
  }

  return (
    <Menu shadow="md" width={160}>
      <Menu.Target>
        <ActionIcon variant="subtle" size="lg">
          {getCurrentIcon()}
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item
          leftSection={<IconSun size={16} />}
          rightSection={preference === "light" ? <IconCheck size={16} /> : null}
          onClick={() => handleSelect("light")}
        >
          {t("light")}
        </Menu.Item>
        <Menu.Item
          leftSection={<IconMoon size={16} />}
          rightSection={preference === "dark" ? <IconCheck size={16} /> : null}
          onClick={() => handleSelect("dark")}
        >
          {t("dark")}
        </Menu.Item>
        <Menu.Item
          leftSection={<IconBrightnessAuto size={16} />}
          rightSection={
            preference === "system" ? <IconCheck size={16} /> : null
          }
          onClick={() => handleSelect("system")}
        >
          {t("system")}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
