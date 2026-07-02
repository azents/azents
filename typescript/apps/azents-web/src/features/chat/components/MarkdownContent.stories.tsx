import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  codeReadabilityMarkdownSample,
  markdownSample,
  mermaidMarkdownSample,
} from "../story-fixtures";
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

export const MermaidDiagram = {
  args: {
    children: mermaidMarkdownSample,
  },
} satisfies Story;
