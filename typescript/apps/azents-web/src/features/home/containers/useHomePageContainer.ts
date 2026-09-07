"use client";

import { useMantineColorScheme } from "@mantine/core";
import { useWindowEvent } from "@mantine/hooks";
import { useState } from "react";
import { useColorMode } from "@/shared/providers/color-mode";
import type { ColorMode } from "@/shared/lib/color-mode";

export interface HomePageContainerOutput {
  captureOpen: boolean;
  menuOpen: boolean;
  mode: ColorMode;
  onCloseCapture: () => void;
  onCloseMenu: () => void;
  onOpenCapture: () => void;
  onToggleMenu: () => void;
  onToggleTheme: () => void;
}

export function useHomePageContainer(): HomePageContainerOutput {
  const [menuOpen, setMenuOpen] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);
  const { mode, setColorMode } = useColorMode();
  const { setColorScheme } = useMantineColorScheme();

  function closeMenu(): void {
    setMenuOpen(false);
  }

  function toggleTheme(): void {
    const nextMode = mode === "dark" ? "light" : "dark";
    setColorMode(nextMode);
    setColorScheme(nextMode);
  }

  useWindowEvent("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenu();
    }
  });

  return {
    captureOpen,
    menuOpen,
    mode,
    onCloseCapture: () => setCaptureOpen(false),
    onCloseMenu: closeMenu,
    onOpenCapture: () => setCaptureOpen(true),
    onToggleMenu: () => setMenuOpen((open) => !open),
    onToggleTheme: toggleTheme,
  };
}
