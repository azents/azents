"use client";

/**
 * Color mode switch component.
 *
 * Icon button for selecting light / dark / system modes from menu.
 */
import { ActionIcon, Menu, rem } from "@mantine/core";
import {
  IconBrightnessAuto,
  IconCheck,
  IconMoon,
  IconSun,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useColorModeSwitcherController } from "../containers/useColorModeSwitcherController";
import { createReactContainer } from "../lib/createReactContainer";
import type { ColorModeSwitcherOutput } from "../containers/useColorModeSwitcherController";

export const ColorModeSwitcher = createReactContainer(
  "ColorModeSwitcher",
  useColorModeSwitcherController,
  ColorModeSwitcherView,
);

export function ColorModeSwitcherView({
  mode,
  preference,
  handleSelect,
}: ColorModeSwitcherOutput): React.ReactElement {
  const t = useTranslations("common");

  function getCurrentIcon(): React.ReactElement {
    if (preference === "system") {
      return <IconBrightnessAuto size={rem(20)} />;
    }
    return mode === "dark" ? (
      <IconMoon size={rem(20)} />
    ) : (
      <IconSun size={rem(20)} />
    );
  }

  return (
    <Menu shadow="md" width={rem(160)}>
      <Menu.Target>
        <ActionIcon variant="subtle" size="lg">
          {getCurrentIcon()}
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item
          leftSection={<IconSun size={rem(16)} />}
          rightSection={
            preference === "light" ? <IconCheck size={rem(16)} /> : null
          }
          onClick={() => handleSelect("light")}
        >
          {t("light")}
        </Menu.Item>
        <Menu.Item
          leftSection={<IconMoon size={rem(16)} />}
          rightSection={
            preference === "dark" ? <IconCheck size={rem(16)} /> : null
          }
          onClick={() => handleSelect("dark")}
        >
          {t("dark")}
        </Menu.Item>
        <Menu.Item
          leftSection={<IconBrightnessAuto size={rem(16)} />}
          rightSection={
            preference === "system" ? <IconCheck size={rem(16)} /> : null
          }
          onClick={() => handleSelect("system")}
        >
          {t("system")}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
