import { expect, waitFor } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  codeReadabilityMarkdownSample,
  markdownSample,
  mermaidMarkdownSample,
} from "../markdown-story-fixtures";
import { MarkdownContent } from "./MarkdownContent";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: MarkdownContent,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof MarkdownContent>;

export default meta;

type Story = StoryObj<typeof meta>;

export const RichMarkdown = {
  args: {
    children: markdownSample,
  },
} satisfies Story;

export const InlineText = {
  args: {
    children:
      "A compact assistant message with `inline code` and **emphasis**.",
  },
} satisfies Story;

export const CodeReadability = {
  args: {
    children: codeReadabilityMarkdownSample,
  },
} satisfies Story;

export const SingleLineScrollableCode = {
  args: {
    children:
      "```\nYou may also see them addressed as to=/root/very/long/path/that/keeps/scrolling/without/moving/the/copy/button\n```",
  },
} satisfies Story;

export const MermaidDiagram = {
  tags: ["ci-contract"],
  args: {
    children: mermaidMarkdownSample,
  },
  play: async ({ canvasElement }) => {
    await waitFor(async () => {
      const diagram = canvasElement.querySelector("svg[id^='azents-mermaid-']");
      await expect(diagram).toBeInTheDocument();
      await expect(diagram).toHaveTextContent("Send message");
    });
  },
} satisfies Story;

export const MermaidMath = {
  tags: ["ci-contract"],
  args: {
    children:
      '```mermaid\nflowchart LR\n    A["$$x^2 + y^2 = z^2$$"] --> B["Result"]\n```',
  },
  play: async ({ canvasElement }) => {
    await waitFor(async () => {
      await expect(
        canvasElement.querySelector("svg[id^='azents-mermaid-'] .katex"),
      ).toBeInTheDocument();
    });
  },
} satisfies Story;
