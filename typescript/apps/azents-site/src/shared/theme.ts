import {
  createTheme,
  defaultVariantColorsResolver,
  type MantineColorsTuple,
  rem,
} from "@mantine/core";

const graphite: MantineColorsTuple = [
  "#f4f7fb",
  "#dce4ee",
  "#bac7d6",
  "#93a4b8",
  "#6f8298",
  "#56687c",
  "#3d4b5c",
  "#17202b",
  "#0c121a",
  "#070a0f",
];

const signal: MantineColorsTuple = [
  "#edf4ff",
  "#d8e7ff",
  "#adcaff",
  "#82aafa",
  "#668feb",
  "#5378d4",
  "#405fb0",
  "#334a86",
  "#26365f",
  "#19243f",
];

const dark: MantineColorsTuple = [
  "#f4f7fb",
  "#d4dde9",
  "#9aaabc",
  "#6f8196",
  "#435266",
  "#242d3a",
  "#151c27",
  "#0a0f18",
  "#070a0f",
  "#040609",
];

export const theme = createTheme({
  white: "#f4f7fb",
  black: "#070a0f",
  colors: {
    dark,
    graphite,
    signal,
  },
  spacing: {
    "2xs": rem(6),
    "2xl": rem(40),
    "3xl": rem(56),
    "4xl": rem(64),
    "5xl": rem(100),
    "6xl": rem(120),
    "7xl": rem(156),
  },
  primaryColor: "signal",
  primaryShade: { light: 6, dark: 2 },
  autoContrast: true,
  variantColorResolver: (input) => {
    const resolved = defaultVariantColorsResolver(input);
    if (input.variant === "filled") {
      resolved.color =
        "light-dark(var(--mantine-color-white), var(--mantine-color-black))";
    }
    return resolved;
  },
  fontFamily: "var(--font-azents-sans)",
  headings: {
    fontFamily: "var(--font-azents-sans)",
    fontWeight: "650",
  },
  fontFamilyMonospace: "var(--font-azents-mono)",
});
