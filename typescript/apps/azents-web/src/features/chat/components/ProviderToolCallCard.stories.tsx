import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { binaryAttachment, imageAttachment } from "../story-fixtures";
import { ProviderToolCallCard } from "./ProviderToolCallCard";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ProviderToolCallCard,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ProviderToolCallCard>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Running = {
  args: {
    toolCall: {
      id: "provider-call-1",
      callId: "provider-call-1",
      name: "web_search",
      arguments: '{"query":"Azents"}',
      status: "running",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Web search")).toBeVisible();
    await expect(canvas.getByText("Searching the web")).toBeVisible();
    await expect(canvas.getByLabelText("Running")).toBeVisible();
  },
} satisfies Story;

export const WebSearchResults = {
  args: {
    toolCall: {
      id: "provider-search-results",
      callId: "provider-search-results",
      name: "web_search",
      arguments:
        '{"queries":["  Azents   agent platform  ","site:docs.example.com\\nagent workflows"]}',
      status: "completed",
      semanticOutput: "Found two relevant sources.",
      references: [
        {
          kind: "url",
          uri: "https://example.com/overview",
          title: "Azents overview",
          excerpt: "An overview of the Azents agent platform.",
          metadata: {},
        },
        {
          kind: "url",
          uri: "https://example.com/docs",
          title: "Azents documentation",
          excerpt: "Guides for configuring agent workflows.",
          metadata: {},
        },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Web search/ }));
    await expect(canvas.getByText("Azents agent platform")).toBeVisible();
    await expect(
      canvas.getByText("site:docs.example.com agent workflows"),
    ).toBeVisible();
    await expect(canvas.getByText("Azents overview")).toBeVisible();
    await expect(canvas.getByText("Azents documentation")).toBeVisible();
  },
} satisfies Story;

export const CompletedWithOutputAndAttachment = {
  args: {
    toolCall: {
      id: "provider-call-2",
      callId: "provider-call-2",
      name: "image_generation",
      arguments: '{"prompt":"A reliable timeline"}',
      status: "completed",
      output: "Generated one image.",
      attachments: [imageAttachment],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = canvasElement.querySelector(
      '[data-provider-tool-name="image_generation"]',
    );
    await expect(card).toHaveAttribute(
      "data-provider-tool-status",
      "completed",
    );
    await expect(canvas.getByText(imageAttachment.name ?? "")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Show tool details" }),
    );
    await expect(canvas.getByText("Generated one image.")).toBeVisible();
  },
} satisfies Story;

export const CompletedWithGenericAttachment = {
  args: {
    toolCall: {
      id: "provider-call-3",
      callId: "provider-call-3",
      name: "custom_retrieval",
      arguments: '{"query":"release artifacts"}',
      status: "completed",
      output: "Retrieved one artifact.",
      attachments: [binaryAttachment],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Custom retrieval")).toBeVisible();
    await expect(canvas.getByText(binaryAttachment.name ?? "")).toBeVisible();
  },
} satisfies Story;

export const Failed = {
  args: {
    toolCall: {
      id: "provider-call-4",
      callId: "provider-call-4",
      name: "web_search",
      arguments: "",
      status: "failed",
      output: "The provider rejected the request.",
    },
  },
} satisfies Story;

export const UnknownHistoricalStatus = {
  args: {
    toolCall: {
      id: "provider-call-5",
      callId: "provider-call-5",
      name: "custom_retrieval",
      arguments: "",
      status: "unknown",
    },
  },
} satisfies Story;
