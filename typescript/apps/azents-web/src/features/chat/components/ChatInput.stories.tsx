import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { pendingFiles } from "../story-fixtures";
import { ChatInput } from "./ChatInput";
import type { UploadedFile } from "../hooks/useFileUpload";
import type { SlashCommand } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const uploadAll = (): Promise<UploadedFile[]> => Promise.resolve([]);
const sendMessage = (): Promise<boolean> => Promise.resolve(true);
const sendCommand = (): Promise<boolean> => Promise.resolve(true);
const clearDoneFiles = (): void => {};
const resetDoneFiles = (): void => {};
const addFiles: (files: FileList) => void = () => {};
const removeFile = (): void => {};
const afterSend = (): void => {};
const stopRequest = (): void => {};
const slashCommands: SlashCommand[] = [
  {
    name: "compact",
    description:
      "Summarize previous conversation and compact the context window.",
  },
];

const meta = {
  component: ChatInput,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(860)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ChatInput>;

export default meta;

type Story = StoryObj<typeof meta>;

const baseArgs = {
  agentId: "story-agent-001",
  sessionId: "story-session-001",
  isMobile: false,
  isUploading: false,
  pendingFiles: [],
  goal: null,
  todo: null,
  uploadAll,
  onSendMessage: sendMessage,
  onSendCommand: sendCommand,
  clearDoneFiles,
  resetDoneFiles,
  addFiles,
  removeFile,
  onAfterSend: afterSend,
  wasCommandBlocked: false,
  isStopAvailable: false,
  isStopPending: false,
  onStopRequest: stopRequest,
  slashCommands,
};

export const Ready = {
  args: baseArgs,
} satisfies Story;

export const WithPendingFiles = {
  args: {
    ...baseArgs,
    pendingFiles,
  },
} satisfies Story;

export const WaitingForResponse = {
  args: {
    ...baseArgs,
    isStopAvailable: true,
  },
} satisfies Story;

export const CommandBlocked = {
  args: {
    ...baseArgs,
    wasCommandBlocked: true,
  },
} satisfies Story;

export const SlashCommandSuggestions = {
  args: {
    ...baseArgs,
    initialInputValue: "/",
  },
} satisfies Story;

export const EditingMessage = {
  args: {
    ...baseArgs,
    editingMessageId: "user-message-001",
    editingInitialValue: "Please summarize only the failed checks.",
  },
} satisfies Story;

export const EditingBlockedByRun = {
  args: {
    ...baseArgs,
    editingMessageId: "user-message-001",
    editingInitialValue: "Please summarize only the failed checks.",
    editSendDisabled: true,
  },
} satisfies Story;
