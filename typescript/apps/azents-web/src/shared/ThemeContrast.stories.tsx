import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Chip,
  Group,
  Paper,
  Radio,
  Stack,
  Switch,
  Text,
  ThemeIcon,
} from "@mantine/core";
import { expect, waitFor } from "storybook/test";
import { expectReadableContrast } from "./storybook/contrast";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const colors = [
  void 0,
  "mono",
  "green",
  "red",
  "yellow",
  "blue",
  "gray",
  "mono.0",
  "mono.9",
  "teal.9",
  "gray.7",
  "white",
  "black",
  "violet.7",
  "green.8",
  "blue.8",
  "orange.9",
  "blue.6",
  "blue.7",
  "red.8",
  "teal.8",
  "violet.5",
];

function ThemeContrast(): React.ReactElement {
  return (
    <Stack p="md">
      {colors.map((color) => (
        <Group key={color ?? "default"}>
          <Badge color={color} data-contrast>
            {color ?? "Default"}
          </Badge>
          <Button color={color} data-contrast>
            Button
          </Button>
          <ActionIcon
            color={color}
            aria-label={`${color ?? "Default"} action`}
            data-contrast
          >
            A
          </ActionIcon>
          <ThemeIcon color={color} data-contrast>
            T
          </ThemeIcon>
          <Chip color={color} variant="filled" defaultChecked>
            Chip
          </Chip>
          <Checkbox color={color} label="Checkbox" defaultChecked />
          <Radio color={color} label="Radio" defaultChecked />
          <Switch color={color} label="Switch" onLabel="ON" defaultChecked />
        </Group>
      ))}
      <Paper variant="message" data-contrast>
        Human message
      </Paper>
      <Box
        bg="var(--azents-color-inverse)"
        c="var(--azents-color-on-inverse)"
        data-contrast
      >
        Inverse surface
      </Box>
      <Text c="dimmed" data-muted>
        Secondary information
      </Text>
    </Stack>
  );
}

const meta = {
  title: "Theme/Contrast",
  component: ThemeContrast,
  tags: ["ci-contract"],
  parameters: { a11y: { test: "error" } },
} satisfies Meta<typeof ThemeContrast>;
export default meta;
type Story = StoryObj<typeof meta>;

async function assertContrast(
  canvasElement: HTMLElement,
  mode: "light" | "dark",
): Promise<void> {
  await waitFor(async () => {
    await expect(canvasElement.ownerDocument.documentElement).toHaveAttribute(
      "data-mantine-color-scheme",
      mode,
    );
    const controls = canvasElement.querySelectorAll("[data-contrast]");
    await expect(controls).toHaveLength(colors.length * 4 + 2);
    for (const control of controls) {
      await expectReadableContrast(control);
    }
    for (const chip of canvasElement.querySelectorAll(".mantine-Chip-label")) {
      await expectReadableContrast(chip);
    }
    for (const input of canvasElement.querySelectorAll(
      ".mantine-Checkbox-input, .mantine-Radio-radio",
    )) {
      const icon = input.parentElement?.querySelector("svg");
      if (icon == null) {
        throw new Error("Missing checked control icon");
      }
      await expectReadableContrast(icon, input);
    }
    for (const track of canvasElement.querySelectorAll(
      ".mantine-Switch-track",
    )) {
      await expectReadableContrast(track);
    }
    const muted = canvasElement.querySelector("[data-muted]");
    const surface = canvasElement.querySelector(".storybook-surface");
    if (muted == null || surface == null) {
      throw new Error("Missing theme surface");
    }
    await expectReadableContrast(muted, surface);
  });
}

export const Light: Story = {
  globals: { colorScheme: "light" },
  play: async ({ canvasElement }) => assertContrast(canvasElement, "light"),
};
export const Dark: Story = {
  globals: { colorScheme: "dark" },
  play: async ({ canvasElement }) => assertContrast(canvasElement, "dark"),
};

async function assertHoverContrast(
  canvasElement: HTMLElement,
  mode: "light" | "dark",
): Promise<void> {
  await assertContrast(canvasElement, mode);
  if (import.meta.env.MODE !== "test") {
    return;
  }
  // Native pointer movement is required: synthetic mouseover does not set :hover.
  const { userEvent } = await import("vitest/browser");
  const controls = canvasElement.querySelectorAll(
    ".mantine-Button-root, .mantine-ActionIcon-root, .mantine-Chip-label",
  );
  await expect(controls).toHaveLength(colors.length * 3);
  for (const control of controls) {
    await userEvent.hover(control);
    await expect(control.matches(":hover")).toBe(true);
    await waitFor(async () => expectReadableContrast(control));
    await userEvent.unhover(control);
  }
}

export const HoverLight: Story = {
  globals: { colorScheme: "light" },
  play: async ({ canvasElement }) =>
    assertHoverContrast(canvasElement, "light"),
};
export const HoverDark: Story = {
  globals: { colorScheme: "dark" },
  play: async ({ canvasElement }) => assertHoverContrast(canvasElement, "dark"),
};

function ExplicitOverrides(): React.ReactElement {
  return (
    <Stack p="md">
      <Badge color="red.9" autoContrast={false} data-opt-out>
        Opt out
      </Badge>
      <Text c="white" data-white>
        White reference
      </Text>
      <Checkbox defaultChecked iconColor="blue.9" label="Explicit icon" />
      <Text c="blue.9" data-blue>
        Blue reference
      </Text>
      <Badge color="green" variant="light" data-light>
        Light variant
      </Badge>
      <Text c="var(--mantine-color-green-light-color)" data-light-reference>
        Light reference
      </Text>
      <Badge color="green" variant="outline" data-outline>
        Outline variant
      </Badge>
      <Text c="var(--mantine-color-green-outline)" data-outline-reference>
        Outline reference
      </Text>
    </Stack>
  );
}

async function assertOverrides(canvasElement: HTMLElement): Promise<void> {
  function color(selector: string): string {
    const element = canvasElement.querySelector(selector);
    if (element == null) {
      throw new Error(`Missing ${selector}`);
    }
    return getComputedStyle(element).color;
  }
  await waitFor(async () => {
    await expect(color("[data-opt-out]")).toBe(color("[data-white]"));
    await expect(color(".mantine-Checkbox-icon")).toBe(color("[data-blue]"));
    await expect(color("[data-light]")).toBe(color("[data-light-reference]"));
    await expect(color("[data-outline]")).toBe(
      color("[data-outline-reference]"),
    );
  });
}

export const OverridesLight: Story = {
  globals: { colorScheme: "light" },
  render: () => <ExplicitOverrides />,
  // Explicit caller choices are tested for preservation, not automatic contrast.
  parameters: { a11y: { test: "off" } },
  play: async ({ canvasElement }) => assertOverrides(canvasElement),
};
export const OverridesDark: Story = {
  ...OverridesLight,
  globals: { colorScheme: "dark" },
};
