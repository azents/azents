import {
  Checkbox,
  createTheme,
  defaultVariantColorsResolver,
  type MantineColorsTuple,
  rem,
  Switch,
} from "@mantine/core";

/**
 * azents-web theme.
 *
 * "Dark Canvas" design:
 * - Geist Sans for headlines + body — Vercel-style clean typography
 * - Geist Mono for labels/code/agent names — technical precision
 * - Dark theme by default — #000 background, #ededed text
 *
 * Font CSS variables are injected by the geist package in layout.tsx.
 */

/**
 * Warm monochrome custom palette.
 *
 * Mantine built-in gray is used by base UI elements, so using it as
 * primaryColor can conflict with other UI elements. Define a custom palette.
 * Warm gray tone that pairs with light mode white (#f7f3ed).
 */
const mono: MantineColorsTuple = [
  "#f9f7f4",
  "#f2f0ec",
  "#eae7e2",
  "#dfdbd5",
  "#d0cbc4",
  "#afa9a1",
  "#8a847c",
  "#4d4841",
  "#38342e",
  "#25221d",
];

/**
 * Dark palette aligned with the Dark Canvas design system.
 *
 * Adjusted to higher brightness and warmer tone.
 * Mantine dark mode CSS variable mapping:
 * - dark[0] → --mantine-color-text (#efece8)
 * - dark[2] → --mantine-color-dimmed (#9b9690)
 * - dark[4] → --mantine-color-default-border (#353230)
 * - dark[6] → --mantine-color-default (#1a1917)
 * - dark[7] → --mantine-color-body (#0c0b09)
 */
const dark: MantineColorsTuple = [
  "#efece8",
  "#cec9c3",
  "#9b9690",
  "#686461",
  "#353230",
  "#242220",
  "#1a1917",
  "#0c0b09",
  "#070605",
  "#050403",
];

export const theme = createTheme({
  /** Warm-toned light mode background instead of pure white */
  white: "#f7f3ed",
  black: "#0c0b09",
  colors: {
    mono,
    dark,
  },
  /**
   * Extended spacing scale.
   *
   * Keeps Mantine defaults (xs=10, sm=12, md=16, lg=20, xl=32),
   * and adds values repeatedly used in the project as custom tokens.
   * Accessible through CSS variable: --mantine-spacing-{token}.
   */
  spacing: {
    "2xs": rem(6),
    "2xl": rem(40),
    "3xl": rem(56),
    "4xl": rem(64),
    "5xl": rem(100),
    "6xl": rem(120),
  },
  primaryColor: "mono",
  primaryShade: { light: 9, dark: 0 },
  autoContrast: true,
  /**
   * Mantine defaultVariantColorsResolver does not pass colorScheme when calling
   * parseThemeColor, so isLight is always calculated with the light-mode shade.
   * When primaryShade differs by mode, filled variant text color becomes wrong;
   * correct it for runtime colorScheme with CSS light-dark().
   */
  variantColorResolver: (input) => {
    const resolved = defaultVariantColorsResolver(input);
    if (input.variant === "filled") {
      resolved.color =
        "light-dark(var(--mantine-color-white), var(--mantine-color-black))";
    }
    return resolved;
  },
  fontFamily:
    "var(--font-geist-sans, -apple-system), BlinkMacSystemFont, 'Segoe UI', sans-serif",
  headings: {
    fontFamily:
      "var(--font-geist-sans, -apple-system), BlinkMacSystemFont, 'Segoe UI', sans-serif",
    fontWeight: "600",
  },
  fontFamilyMonospace: "var(--font-geist-mono, 'Menlo'), 'Consolas', monospace",
  components: {
    Checkbox: Checkbox.extend({
      styles: {
        icon: {
          color:
            "light-dark(var(--mantine-color-white), var(--mantine-color-black))",
        },
      },
    }),
    Switch: Switch.extend({
      styles: {
        root: {
          "--switch-color":
            "light-dark(var(--mantine-primary-color-filled), var(--mantine-color-mono-6))",
        },
      },
    }),
  },
});
