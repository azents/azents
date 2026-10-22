import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Chip,
  createTheme,
  darken,
  defaultVariantColorsResolver,
  getPrimaryShade,
  luminance,
  type MantineColorsTuple,
  type MantineTheme,
  Paper,
  parseThemeColor,
  Radio,
  rem,
  Switch,
  ThemeIcon,
} from "@mantine/core";
import classes from "./theme.module.css";
import type { CSSVariablesResolver } from "@mantine/core";

function filledForeground(
  theme: MantineTheme,
  color?: string,
  autoContrast?: boolean,
  hovered = false,
): string {
  if (!(autoContrast ?? theme.autoContrast)) {
    return "var(--mantine-color-white)";
  }
  function foreground(colorScheme: "light" | "dark"): string {
    const parsed = parseThemeColor({
      theme,
      color: color ?? theme.primaryColor,
      colorScheme,
    });
    let fill = parsed.value;
    if (hovered) {
      if (parsed.isThemeColor) {
        const shade = parsed.shade ?? getPrimaryShade(theme, colorScheme);
        // Mantine's filled-hover token advances one shade, wrapping 9 to 8.
        fill =
          theme.colors[parsed.color]?.[shade === 9 ? 8 : shade + 1] ?? fill;
      } else {
        fill = darken(color ?? theme.primaryColor, 0.1);
      }
    }
    // The crossover gives the higher WCAG contrast of pure black and white.
    return luminance(fill) > Math.sqrt(0.05 * 1.05) - 0.05
      ? "var(--azents-color-contrast-dark)"
      : "var(--azents-color-contrast-light)";
  }
  const light = foreground("light");
  const dark = foreground("dark");
  return `light-dark(${light}, ${dark})`;
}

/** Shared semantic surfaces keep screen styles independent of palette shades. */
export const themeCssVariables: CSSVariablesResolver = (theme) => ({
  variables: {
    "--azents-color-contrast-dark": "#000000",
    "--azents-color-contrast-light": "#ffffff",
    "--azents-color-inverse": "var(--mantine-color-gray-9)",
    "--azents-color-on-inverse": filledForeground(theme, "gray.9"),
    "--azents-color-inverse-muted": "var(--mantine-color-gray-5)",
  },
  light: {
    "--mantine-color-dimmed": "var(--mantine-color-gray-7)",
    "--azents-color-canvas": "var(--mantine-color-mono-1)",
    "--azents-color-surface": "var(--mantine-color-white)",
    "--azents-color-surface-raised": "var(--mantine-color-white)",
    "--azents-color-surface-hover": "var(--mantine-color-mono-0)",
    "--azents-color-border": "var(--mantine-color-mono-3)",
    "--azents-color-border-strong": "var(--mantine-color-mono-5)",
    "--azents-color-muted": "var(--mantine-color-mono-7)",
    "--azents-color-subtle": "var(--mantine-color-mono-8)",
    "--azents-color-error": "var(--mantine-color-red-7)",
  },
  dark: {
    "--mantine-color-dimmed": "var(--mantine-color-dark-1)",
    "--azents-color-canvas": "var(--mantine-color-dark-8)",
    "--azents-color-surface": "var(--mantine-color-dark-6)",
    "--azents-color-surface-raised": "var(--mantine-color-dark-5)",
    "--azents-color-surface-hover": "var(--mantine-color-dark-4)",
    "--azents-color-border": "var(--mantine-color-dark-4)",
    "--azents-color-border-strong": "var(--mantine-color-dark-3)",
    "--azents-color-muted": "var(--mantine-color-dark-1)",
    "--azents-color-subtle": "var(--mantine-color-dark-2)",
    "--azents-color-error": "var(--mantine-color-red-4)",
  },
});

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
 * - dark[1] → --mantine-color-dimmed (#cec9c3, shared readable secondary text)
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
   * Resolve foreground from each mode's actual fill, including explicit shades.
   */
  variantColorResolver: (input) => {
    const resolved = defaultVariantColorsResolver(input);
    if (input.variant === "filled") {
      resolved.color = filledForeground(
        input.theme,
        input.color,
        input.autoContrast,
      );
      resolved.hoverColor = filledForeground(
        input.theme,
        input.color,
        input.autoContrast,
        true,
      );
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
    // These components omit resolved foreground variables without a variant/color.
    Badge: Badge.extend({ defaultProps: { variant: "filled" } }),
    Button: Button.extend({ defaultProps: { variant: "filled" } }),
    ActionIcon: ActionIcon.extend({ defaultProps: { variant: "filled" } }),
    ThemeIcon: ThemeIcon.extend({ defaultProps: { variant: "filled" } }),
    Chip: Chip.extend({
      defaultProps: { variant: "filled" },
      classNames: (_theme, props) => ({
        label: props.variant === "filled" ? classes.chipLabel : void 0,
      }),
      styles: (theme, props) => ({
        root: {
          "--azents-chip-hover-foreground":
            props.variant === "filled"
              ? filledForeground(theme, props.color, props.autoContrast, true)
              : void 0,
        },
      }),
    }),
    Paper: Paper.extend({
      styles: (theme, props) => ({
        root:
          props.variant === "message"
            ? {
                backgroundColor: "var(--mantine-color-blue-6)",
                color: filledForeground(theme, "blue.6"),
              }
            : {},
      }),
    }),
    Checkbox: Checkbox.extend({
      vars: (theme, props) => ({
        root: {
          "--checkbox-icon-color":
            props.iconColor || props.variant === "outline"
              ? void 0
              : filledForeground(theme, props.color, props.autoContrast),
        },
      }),
    }),
    Radio: Radio.extend({
      vars: (theme, props) => ({
        root: {
          "--radio-icon-color":
            props.iconColor || props.variant === "outline"
              ? void 0
              : filledForeground(theme, props.color, props.autoContrast),
        },
      }),
    }),
    Switch: Switch.extend({
      classNames: { input: classes.switchInput, track: classes.switchTrack },
      styles: (theme, props) => ({
        root: {
          "--azents-switch-foreground": filledForeground(theme, props.color),
        },
      }),
    }),
  },
});
