import { expect, userEvent, within } from "storybook/test";
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
    await userEvent.click(canvas.getByRole("button", { name: /Ran command/ }));
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
    await userEvent.click(canvas.getByRole("button", { name: /Ran command/ }));
    await expect(
      canvas.getByText("$ pnpm --filter @azents/web test"),
    ).toBeVisible();
    await expect(canvas.getByText("66 tests passed")).toBeVisible();
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
        ],
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
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
