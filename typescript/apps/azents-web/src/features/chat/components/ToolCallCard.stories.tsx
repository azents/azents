import { Box, rem } from "@mantine/core";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  attachmentToolCall,
  completedToolCall,
  failedToolCall,
  interruptedToolCall,
  preparingToolCall,
  runningToolCall,
} from "../story-fixtures";
import { ToolCallCard } from "./ToolCallCard";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ToolCallCard,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ToolCallCard>;

export default meta;

type Story = StoryObj<typeof meta>;

const longCommandResult = Array.from(
  { length: 80 },
  (_, index) => `log line ${index + 1}: completed command output`,
).join("\n");

const longJavaScriptFileContent = Array.from(
  { length: 80 },
  (_, index) =>
    `export const mobileViewport${index + 1} = { width: 390, height: 844 };`,
).join("\n");

export const Preparing = {
  args: {
    toolCall: preparingToolCall,
  },
} satisfies Story;

export const Running = {
  args: {
    toolCall: runningToolCall,
  },
} satisfies Story;

export const Completed = {
  args: {
    toolCall: completedToolCall,
  },
} satisfies Story;

export const RunningCommandExpanded = {
  args: {
    toolCall: {
      id: "running-command-story",
      callId: "running-command-story",
      name: "exec_command",
      arguments: '{"command":"pnpm --filter @azents/web dev"}',
      status: "running",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /^Ran command/ }));
    await expect(
      canvas.getByText("$ pnpm --filter @azents/web dev"),
    ).toBeVisible();
  },
} satisfies Story;

export const CompletedCommandExpanded = {
  args: {
    toolCall: {
      id: "completed-command-story",
      callId: "completed-command-story",
      name: "exec_command",
      arguments: '{"command":"pnpm --filter @azents/web test"}',
      result: "66 tests passed",
      resultMetadata: {
        kind: "exec_command_result",
        status: "completed",
        exit_code: 0,
        stdout_truncated: false,
        stderr_truncated: false,
      },
      status: "completed",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /^Ran command/ }));
    await expect(
      canvas.getByText("$ pnpm --filter @azents/web test"),
    ).toBeVisible();
    await expect(canvas.getByText("66 tests passed")).toBeVisible();
  },
} satisfies Story;

export const NestedCommandScrollContainment = {
  args: {
    toolCall: {
      id: "nested-command-scroll-story",
      callId: "nested-command-scroll-story",
      name: "exec_command",
      arguments: '{"command":"pnpm --filter @azents/web test"}',
      result: longCommandResult,
      resultMetadata: {
        kind: "exec_command_result",
        status: "completed",
        exit_code: 0,
        stdout_truncated: false,
        stderr_truncated: false,
      },
      status: "completed",
    },
  },
  decorators: [
    (Story) => (
      <Box
        h={rem(360)}
        data-tool-scroll-background
        style={{ overflowY: "auto" }}
      >
        <Story />
        <Box h={rem(480)} />
      </Box>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /^Ran command/ }));
    const viewport = canvasElement.querySelector(
      "[data-activity-detail-scroll-viewport]",
    );
    if (!(viewport instanceof HTMLElement)) {
      throw new Error("Expected the Activity detail scroll viewport");
    }
    await expect(getComputedStyle(viewport).overscrollBehavior).toBe("contain");
    Object.defineProperties(viewport, {
      clientHeight: { configurable: true, value: 120 },
      scrollHeight: { configurable: true, value: 480 },
      scrollTop: { configurable: true, value: 360, writable: true },
    });
    await expect(fireEvent.wheel(viewport, { deltaY: 80 })).toBe(false);
    await expect(
      fireEvent.touchStart(viewport, {
        touches: [{ clientY: 120 }],
      }),
    ).toBe(true);
    await expect(
      fireEvent.touchMove(viewport, {
        touches: [{ clientY: 80 }],
      }),
    ).toBe(false);
  },
} satisfies Story;

export const PresentedFiles = {
  args: {
    toolCall: {
      id: "presented-files-story",
      callId: "presented-files-story",
      name: "present_file",
      arguments: '{"paths":["/workspace/agent/reports/activity-review.md"]}',
      result: "Presented one file.",
      status: "completed",
      attachments: [
        {
          attachmentId: "presented-file",
          uri: "exchange://generated/activity-review.md",
          mediaType: "text/markdown",
          name: "activity-review.md",
        },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Presented files")).toBeVisible();
    await expect(canvas.getByText("activity-review.md")).toBeVisible();
  },
} satisfies Story;

export const KnownWriteUsesEditIcon = {
  args: {
    toolCall: {
      id: "known-write-story",
      callId: "known-write-story",
      name: "write",
      arguments: JSON.stringify({
        path: "/workspace/agent/mobile-scroll-playwright.config.js",
        content: longJavaScriptFileContent,
      }),
      result: "File written.",
      status: "completed",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Wrote file")).toBeVisible();
    await expect(
      canvas.getByText("mobile-scroll-playwright.config.js"),
    ).toBeVisible();
    await expect(
      canvasElement.querySelector(".tabler-icon-pencil"),
    ).not.toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: /^Wrote file/ }));
    await expect(canvas.getByText(/export const mobileViewport/)).toBeVisible();
    await expect(canvasElement.querySelector("pre code span")).not.toBeNull();
    const highlightedCode = canvasElement.querySelector("pre");
    if (!(highlightedCode instanceof HTMLElement)) {
      throw new Error("Expected the highlighted code block");
    }
    const fontSizeReference = document.createElement("span");
    fontSizeReference.style.fontSize = "var(--mantine-font-size-xs)";
    canvasElement.append(fontSizeReference);
    await expect(getComputedStyle(highlightedCode).fontSize).toBe(
      getComputedStyle(fontSizeReference).fontSize,
    );
    fontSizeReference.remove();
  },
} satisfies Story;

export const Failed = {
  args: {
    toolCall: failedToolCall,
  },
} satisfies Story;

export const GenericFailureExpanded = {
  args: {
    toolCall: {
      id: "generic-failure-story",
      callId: "generic-failure-story",
      name: "custom_database_query",
      arguments: '{"query":"select status from jobs"}',
      result: "Connection refused",
      status: "failed",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: /custom_database_query/ }),
    );
    await expect(canvas.getByText("Connection refused")).toBeVisible();
  },
} satisfies Story;

export const KnownGrepVerticalFields = {
  args: {
    toolCall: {
      id: "known-grep-vertical-fields-story",
      callId: "known-grep-vertical-fields-story",
      name: "grep",
      arguments:
        '{"pattern":"NestedCommandScrollContainment|LongMobileConversation","path":"/workspace/agent/azents/typescript/apps/azents-web/storybook-static/index.json"}',
      result: "Found both mobile scroll stories.",
      status: "completed",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /^Grep/ }));

    const queryLabel = canvas.getByText("Query");
    const queryValue = canvas.getByText(
      "NestedCommandScrollContainment|LongMobileConversation",
    );
    const sourceLabel = canvas.getByText("Source");
    const sourceValue = canvas.getByText(
      "/workspace/agent/azents/typescript/apps/azents-web/storybook-static/index.json",
    );

    await expect(queryLabel.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      queryValue.getBoundingClientRect().top,
    );
    await expect(
      sourceLabel.getBoundingClientRect().bottom,
    ).toBeLessThanOrEqual(sourceValue.getBoundingClientRect().top);
    await expect(
      canvas.getByText("Found both mobile scroll stories."),
    ).toBeVisible();
  },
} satisfies Story;

export const Interrupted = {
  args: {
    toolCall: interruptedToolCall,
  },
} satisfies Story;

export const CompletedWithAttachments = {
  args: {
    toolCall: attachmentToolCall,
  },
} satisfies Story;

export const KnownReadWithRawData = {
  args: {
    toolCall: {
      id: "known-read-story",
      callId: "known-read-story",
      name: "read",
      arguments:
        '{"path":"/workspace/agent/azents/src/features/chat/types.ts","offset":1200}',
      status: "completed",
      result: "export interface ActiveToolCall {\n  id: string;\n}",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Read")).toBeVisible();
    await expect(canvas.getByText("types.ts")).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: /Read/ }));
    await expect(
      canvas.getByText("export interface ActiveToolCall"),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "View raw data for Read" }),
    );
    await expect(within(document.body).getByText("Raw data")).toBeVisible();
    await expect(within(document.body).getByText("Tool name")).toBeVisible();
    await expect(within(document.body).getByText("read")).toBeVisible();
  },
} satisfies Story;

export const GenericRawDataWithoutPayload = {
  args: {
    toolCall: {
      id: "generic-raw-data-without-payload",
      callId: "generic-raw-data-without-payload",
      name: "custom_database_query",
      arguments: "",
      status: "completed",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", {
        name: "View raw data for custom_database_query",
      }),
    );
    await expect(within(document.body).getByText("Raw data")).toBeVisible();
    await expect(within(document.body).getByText("Tool name")).toBeVisible();
    await expect(
      within(document.body).getByText("custom_database_query"),
    ).toBeVisible();
  },
} satisfies Story;

export const KnownPatch = {
  args: {
    toolCall: {
      id: "known-patch-story",
      callId: "known-patch-story",
      name: "apply_patch",
      arguments:
        '{"base_path":"/workspace/agent/azents","patch":"*** Begin Patch\\n*** Update File: src/features/chat/components/ToolCallCard.tsx\\n@@\\n-old value\\n+new value\\n*** Add File: src/features/chat/components/PatchPreview.tsx\\n+export const patchPreview = true;\\n*** Delete File: src/features/chat/components/LegacyPatchPreview.tsx\\n*** End Patch"}',
      status: "completed",
      result: "Applied patch under /workspace/agent/azents.",
      resultMetadata: {
        kind: "apply_patch_result",
        changes: [
          {
            action: "update",
            path: "/workspace/agent/azents/src/features/chat/ToolCallCard.tsx",
            added_lines: 12,
            removed_lines: 4,
          },
          {
            action: "add",
            path: "/workspace/agent/azents/src/features/chat/PatchPreview.tsx",
            added_lines: 1,
            removed_lines: 0,
          },
          {
            action: "delete",
            path: "/workspace/agent/azents/src/features/chat/LegacyPatchPreview.tsx",
            added_lines: 0,
            removed_lines: 20,
          },
        ],
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("ToolCallCard.tsx +2")).toBeVisible();
    await expect(canvas.queryByText(/file\(s\) changed/)).toBeNull();
    await userEvent.click(
      canvas.getByRole("button", { name: /Applied patch/ }),
    );
    await expect(
      canvas.getByText("src/features/chat/components/PatchPreview.tsx"),
    ).toBeVisible();
    await expect(
      canvas.getByText("export const patchPreview = true;"),
    ).toBeVisible();
  },
} satisfies Story;

export const KnownEdit = {
  args: {
    toolCall: {
      id: "known-edit-story",
      callId: "known-edit-story",
      name: "edit",
      arguments:
        '{"path":"/workspace/agent/azents/src/features/chat/components/ToolCallCard.tsx","old_string":"fw={600}","new_string":"c=\\"dimmed\\" fw={500}"}',
      status: "completed",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Edited file/ }));
    await expect(canvas.getByText("fw={600}")).toBeVisible();
    await expect(canvas.getByText('c="dimmed" fw={500}')).toBeVisible();
  },
} satisfies Story;

export const KnownEditHorizontalScroll = {
  args: {
    toolCall: {
      id: "known-edit-horizontal-scroll-story",
      callId: "known-edit-horizontal-scroll-story",
      name: "edit",
      arguments: JSON.stringify({
        path: "/workspace/agent/azents/src/features/chat/components/ToolCallCard.tsx",
        old_string: `const previousValue = "${"old-value-".repeat(32)}";`,
        new_string: `const nextValue = "${"new-value-".repeat(32)}";`,
      }),
      status: "completed",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /^Edited file/ }));

    const actionLabel = canvas.getByText("Update");
    const filePath = canvas.getByText(
      "/workspace/agent/azents/src/features/chat/components/ToolCallCard.tsx",
    );
    await expect(
      actionLabel.getBoundingClientRect().bottom,
    ).toBeLessThanOrEqual(filePath.getBoundingClientRect().top);

    const longLine = canvas.getByText(/const nextValue/);
    const viewport = longLine.closest("[data-activity-detail-scroll-viewport]");
    if (!(viewport instanceof HTMLElement)) {
      throw new Error("Expected the diff scroll viewport");
    }
    await expect(getComputedStyle(longLine).whiteSpace).toBe("pre");
    await expect(viewport.scrollWidth).toBeGreaterThan(viewport.clientWidth);
  },
} satisfies Story;
