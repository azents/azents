"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

type ColorMode = "light" | "dark";
type ColorModePreference = "light" | "dark" | "system";

const PREFERENCE_COOKIE = "color-mode-preference";
const RESOLVED_MODE_COOKIE = "color-mode-resolved";

interface ColorModeContextType {
  setColorMode: (preference: ColorModePreference) => void;
  mode: ColorMode;
  preference: ColorModePreference;
}

const ColorModeContext = createContext<ColorModeContextType>({
  setColorMode: () => {},
  mode: "light",
  preference: "system",
});

export const useColorMode = (): ColorModeContextType =>
  useContext(ColorModeContext);

interface ColorModeProviderProps {
  children: ReactNode;
  initialPreference?: ColorModePreference;
  initialResolvedMode?: ColorMode;
}

function getSystemColorMode(): ColorMode {
  if (typeof window === "undefined") {
    return "light";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function setCookie(name: string, value: string, days: number = 365): void {
  if (typeof document === "undefined") {
    return;
  }
  const expires = new Date(
    Date.now() + days * 24 * 60 * 60 * 1000,
  ).toUTCString();
  document.cookie = `${name}=${value}; expires=${expires}; path=/; SameSite=Lax`;
}

export function ColorModeProvider({
  children,
  initialPreference = "system",
  initialResolvedMode = "light",
}: ColorModeProviderProps): ReactNode {
  const [preference, setPreference] =
    useState<ColorModePreference>(initialPreference);
  const [mode, setMode] = useState<ColorMode>(initialResolvedMode);

  // Sync with system preference and save resolved mode to cookie
  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

    const syncMode = (): void => {
      if (preference === "system") {
        const systemMode = getSystemColorMode();
        setMode(systemMode);
        setCookie(RESOLVED_MODE_COOKIE, systemMode);
      }
    };

    // Initial sync
    syncMode();

    // Listen for system preference changes
    const handleChange = (): void => {
      syncMode();
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [preference]);

  const colorMode = useMemo(
    () => ({
      setColorMode: (newPreference: ColorModePreference) => {
        setPreference(newPreference);
        setCookie(PREFERENCE_COOKIE, newPreference);

        if (newPreference === "system") {
          const systemMode = getSystemColorMode();
          setMode(systemMode);
          setCookie(RESOLVED_MODE_COOKIE, systemMode);
        } else {
          setMode(newPreference);
          setCookie(RESOLVED_MODE_COOKIE, newPreference);
        }
      },
      mode,
      preference,
    }),
    [mode, preference],
  );

  return (
    <ColorModeContext.Provider value={colorMode}>
      {children}
    </ColorModeContext.Provider>
  );
}
