import { ChatCodeBlockView } from "./ChatCodeBlock";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  tags: ["ci-contract"],
  component: ChatCodeBlockView,
  args: {
    code: "const answer = 42;",
    language: "typescript",
    codeColorScheme: "light",
  },
} satisfies Meta<typeof ChatCodeBlockView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Light = {} satisfies Story;
export const Dark = { args: { codeColorScheme: "dark" } } satisfies Story;
export const UnknownLanguage = {
  args: { language: "unknown-language", code: "plain text <not HTML>" },
} satisfies Story;
export const Scrollable = {
  args: { maxHeight: "8rem", code: "long output\n".repeat(30) },
} satisfies Story;
