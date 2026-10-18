import { fileURLToPath } from "node:url";
import { storybookTest } from "@storybook/addon-vitest/vitest-plugin";
import { playwright } from "@vitest/browser-playwright";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    storybookTest({
      configDir: fileURLToPath(new URL(".", import.meta.url)),
      tags: { include: ["ci-contract"] },
    }),
  ],
  test: {
    name: "storybook",
    fileParallelism: false,
    maxWorkers: 1,
    browser: {
      enabled: true,
      headless: true,
      provider: playwright(),
      instances: [{ browser: "chromium" }],
    },
  },
});
