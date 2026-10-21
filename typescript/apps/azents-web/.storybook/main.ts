import type { StorybookConfig } from "@storybook/nextjs-vite";

const config: StorybookConfig = {
  viteFinal: (viteConfig) => ({
    ...viteConfig,
    plugins: [
      ...(viteConfig.plugins ?? []),
      {
        name: "native-chat-viewport",
        transformIndexHtml: {
          order: "post",
          handler: (html: string): string =>
            html.replace(
              /(<meta\s+name=["']viewport["']\s+content=["'])[^"']*(["']\s*\/?>)/i,
              "$1width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content$2",
            ),
        },
      },
    ],
  }),
  staticDirs: ["../public"],
  stories: ["../src/**/*.stories.@(ts|tsx|mdx)"],
  addons: [
    "@storybook/addon-docs",
    "@storybook/addon-a11y",
    "@storybook/addon-themes",
    "@storybook/addon-vitest",
  ],
  framework: {
    name: "@storybook/nextjs-vite",
    options: {},
  },
};

export default config;
