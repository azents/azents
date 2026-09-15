import { rem } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RuntimeWebServices } from "./RuntimeWebServices";
import type { RuntimeWebServicesContainerOutput } from "../containers/useRuntimeWebServicesContainer";
import type { RuntimeWebServiceResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};

const offService: RuntimeWebServiceResponse = {
  id: "01a0a4dfd3fb7b88b7ecf202d86f3bd3",
  port: 3000,
  label: "Preview app",
  url: "https://preview.runtime.example.com",
  configuration_state: "configured",
  on: false,
  selected_duration_seconds: 3600,
  expires_at: null,
  revision: 2,
  created_at: "2026-09-15T08:00:00Z",
  updated_at: "2026-09-15T08:30:00Z",
  observed_at: "2026-09-15T08:30:00Z",
};

const onService: RuntimeWebServiceResponse = {
  ...offService,
  id: "01a0a4dfd3fb7b88b7ecf202d86f3bd4",
  port: 5173,
  label: "Design review",
  url: "https://design.runtime.example.com",
  on: true,
  selected_duration_seconds: 21_600,
  expires_at: "2026-09-15T14:30:00Z",
  revision: 7,
};

const baseArgs: RuntimeWebServicesContainerOutput = {
  state: {
    type: "READY",
    services: [onService, offService],
    runtimeAvailable: true,
  },
  action: null,
  mutationError: null,
  onCreate: noop,
  onUpdate: noop,
  onTurnOn: noop,
  onTurnOff: noop,
  onReset: noop,
  onDelete: noop,
};

const meta = {
  component: RuntimeWebServices,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(880)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: baseArgs,
} satisfies Meta<typeof RuntimeWebServices>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Populated = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Web services")).toBeVisible();
    await expect(canvas.getByText("Design review")).toBeVisible();
    await expect(canvas.getByText("Preview app")).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Turn Off" }),
    ).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Turn On" })).toBeVisible();
  },
} satisfies Story;

export const Empty = {
  args: {
    state: { type: "READY", services: [], runtimeAvailable: true },
  },
} satisfies Story;

export const Loading = {
  args: {
    state: { type: "LOADING" },
  },
} satisfies Story;

export const ErrorState = {
  args: {
    state: { type: "ERROR", message: "The service list is unavailable." },
  },
} satisfies Story;

export const RuntimeUnavailable = {
  args: {
    state: {
      type: "READY",
      services: [onService],
      runtimeAvailable: false,
    },
  },
} satisfies Story;

export const CreateDialog = {
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(page.getByRole("button", { name: "Add service" }));
    await expect(
      page.getByRole("dialog", { name: "Add web service" }),
    ).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: "Service name" }),
    ).toBeVisible();
    await expect(
      page.getByRole("switch", { name: "Turn on after creating" }),
    ).toBeVisible();
  },
} satisfies Story;

export const EditDialog = {
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    const editButtons = page.getAllByRole("button", { name: "Edit" });
    const firstEditButton = editButtons.at(0);
    if (!firstEditButton) {
      throw new Error("Expected an Edit button.");
    }
    await userEvent.click(firstEditButton);
    await expect(
      page.getByRole("dialog", { name: "Edit web service" }),
    ).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: "Service name" }),
    ).toHaveValue("Design review");
    await expect(
      page.queryByText(
        "The current expiration will not change until you reset it or turn the service Off and On again.",
      ),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const DeleteDialog = {
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    const deleteButtons = page.getAllByRole("button", { name: "Delete" });
    const firstDeleteButton = deleteButtons.at(0);
    if (!firstDeleteButton) {
      throw new Error("Expected a Delete button.");
    }
    await userEvent.click(firstDeleteButton);
    await expect(
      page.getByRole("dialog", { name: "Delete web service?" }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "This permanently retires the public URL. Recreating the service will generate a different address.",
      ),
    ).toBeVisible();
  },
} satisfies Story;
