import { StorybookProviders } from "../src/shared/storybook/StorybookProviders";
import type { ColorModePreference } from "../src/shared/lib/color-mode";
import type { Preview } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

import "@mantine/core/styles.css";
import "../src/app/globals.css";
import "../src/shared/storybook/storybook.css";

function resolveColorScheme(value: unknown): ColorModePreference {
  if (value === "light" || value === "dark" || value === "system") {
    return value;
  }
  return "system";
}

const preview: Preview = {
  parameters: {
    layout: "fullscreen",
    nextjs: {
      appDirectory: true,
    },
    a11y: {
      test: "todo",
    },
  },
  globalTypes: {
    colorScheme: {
      name: "Color scheme",
      description: "Mantine color scheme",
      defaultValue: "system",
      toolbar: {
        icon: "mirror",
        items: [
          { value: "light", title: "Light" },
          { value: "dark", title: "Dark" },
          { value: "system", title: "System" },
        ],
        dynamicTitle: true,
      },
    },
  },
  initialGlobals: {
    colorScheme: "system",
  },
  decorators: [
    (
      Story: () => ReactElement,
      context: { globals: Record<string, unknown> },
    ): ReactElement => (
      <StorybookProviders
        colorScheme={resolveColorScheme(context.globals.colorScheme)}
      >
        <Story />
      </StorybookProviders>
    ),
  ],
};

export default preview;
