/**
 * Color mode utilities (shared by server/client).
 *
 * Separated from "use client" files so server components can import it too.
 */

export type ColorMode = "light" | "dark";
export type ColorModePreference = "light" | "dark" | "system";

/** Parse ColorModePreference from Cookie value */
export function parseColorModePreference(
  value: string | null,
): ColorModePreference {
  if (value === "light" || value === "dark" || value === "system") {
    return value;
  }
  return "system";
}

/** Parse ColorMode from Cookie value */
export function parseColorMode(value: string | null): ColorMode {
  if (value === "light" || value === "dark") {
    return value;
  }
  return "light";
}
