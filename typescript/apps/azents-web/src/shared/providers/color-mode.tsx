"use client";

/**
 * Color mode context.
 *
 * Stores system / light / dark preference in cookie so SSR can apply it without flicker.
 * Follows the color-mode.tsx pattern from azents-admin-web.
 */
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ColorMode, ColorModePreference } from "@/shared/lib/color-mode";

const PREFERENCE_COOKIE = "color-mode-preference";
const RESOLVED_MODE_COOKIE = "color-mode-resolved";

interface ColorModeContextType {
  /** Current resolved mode (light or dark) */
  mode: ColorMode;
  /** User preference (light, dark, system) */
  preference: ColorModePreference;
  /** Change preference */
  setColorMode: (preference: ColorModePreference) => void;
}

const ColorModeContext = createContext<ColorModeContextType>({
  mode: "light",
  preference: "system",
  setColorMode: () => {},
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

  // Detect system setting changes and synchronize cookie
  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

    const syncMode = (): void => {
      if (preference === "system") {
        const systemMode = getSystemColorMode();
        setMode(systemMode);
        setCookie(RESOLVED_MODE_COOKIE, systemMode);
      }
    };

    syncMode();

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

// parseColorModePreference and parseColorMode are imported from @/shared/lib/color-mode
