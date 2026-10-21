"use client";

import { useMantineColorScheme } from "@mantine/core";
import { useColorMode } from "../providers/color-mode";
import type { ColorModePreference } from "../lib/color-mode";

export interface ColorModeSwitcherOutput {
  mode: "light" | "dark";
  preference: ColorModePreference;
  handleSelect: (preference: ColorModePreference) => void;
}

export function useColorModeSwitcherController(): ColorModeSwitcherOutput {
  const { mode, preference, setColorMode } = useColorMode();
  const { setColorScheme } = useMantineColorScheme();
  function handleSelect(newPreference: ColorModePreference): void {
    setColorMode(newPreference);
    setColorScheme(newPreference === "system" ? "auto" : newPreference);
  }
  return { mode, preference, handleSelect };
}
