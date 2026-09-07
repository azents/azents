import { HomePageContent } from "./components/HomePageContent";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

function noop(): void {}

const meta = {
  component: HomePageContent,
  args: {
    captureOpen: false,
    menuOpen: false,
    mode: "dark",
    onCloseCapture: noop,
    onCloseMenu: noop,
    onOpenCapture: noop,
    onToggleMenu: noop,
    onToggleTheme: noop,
  },
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof HomePageContent>;

export default meta;

type Story = StoryObj<typeof meta>;

export const DarkDesktop = {
  globals: {
    colorScheme: "dark",
  },
} satisfies Story;

export const LightDesktop = {
  args: {
    mode: "light",
  },
  globals: {
    colorScheme: "light",
  },
} satisfies Story;

export const DarkMobile = {
  globals: {
    colorScheme: "dark",
  },
  parameters: {
    viewport: {
      defaultViewport: "mobile1",
    },
  },
} satisfies Story;

export const MobileMenuOpen = {
  args: {
    menuOpen: true,
  },
  globals: {
    colorScheme: "dark",
  },
  parameters: {
    viewport: {
      defaultViewport: "mobile1",
    },
  },
} satisfies Story;

export const CaptureDialogOpen = {
  args: {
    captureOpen: true,
  },
  globals: {
    colorScheme: "dark",
  },
} satisfies Story;
