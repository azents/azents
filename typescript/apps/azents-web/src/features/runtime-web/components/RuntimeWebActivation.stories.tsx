import { Button, rem } from "@mantine/core";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { useRuntimeWebActivationDuration } from "../containers/useRuntimeWebActivationDuration";
import { RuntimeWebActivation } from "./RuntimeWebActivation";
import type { RuntimeWebActivationContainerOutput } from "../containers/useRuntimeWebActivationContainer";
import type { RuntimeWebServiceResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

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

type RuntimeWebActivationStoryProps = Omit<
  RuntimeWebActivationContainerOutput,
  "duration" | "onDurationChange"
>;

function RuntimeWebActivationStory(
  props: RuntimeWebActivationStoryProps,
): React.ReactElement {
  const duration = useRuntimeWebActivationDuration(props.state);
  return <RuntimeWebActivation {...props} {...duration} />;
}

const baseArgs: RuntimeWebActivationStoryProps = {
  applicationUrl: offService.url,
  state: {
    type: "READY",
    service: offService,
    action: null,
    actionError: null,
  },
  onTurnOn: fn(),
  onRetry: fn(),
};

const meta = {
  component: RuntimeWebActivationStory,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(720)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: baseArgs,
} satisfies Meta<typeof RuntimeWebActivationStory>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Off = {
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Turn on web service")).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Turn On" }));
    await expect(args.onTurnOn).toHaveBeenCalledWith(3600);
  },
} satisfies Story;

export const DurationSelection = {
  args: { onTurnOn: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const duration = canvas.getByLabelText("Exposure duration");
    await userEvent.click(duration);
    await userEvent.click(
      within(document.body).getByRole("option", { name: "6 hours" }),
    );
    await expect(duration).toHaveValue("6 hours");
    await userEvent.click(canvas.getByRole("button", { name: "Turn On" }));
    await expect(args.onTurnOn).toHaveBeenCalledWith(21_600);
  },
} satisfies Story;

function RuntimeWebActivationResetStory(
  props: RuntimeWebActivationStoryProps,
): React.ReactElement {
  const [state, setState] = useState(props.state);
  const duration = useRuntimeWebActivationDuration(state);
  return (
    <>
      <RuntimeWebActivation {...props} state={state} {...duration} />
      <Button
        onClick={() =>
          setState((current) =>
            current.type === "READY"
              ? {
                  ...current,
                  service: {
                    ...current.service,
                    selected_duration_seconds: 86_400,
                    revision: current.service.revision + 1,
                  },
                }
              : current,
          )
        }
      >
        Refresh service observation
      </Button>
    </>
  );
}

export const ObservedDurationReset = {
  args: { onTurnOn: fn() },
  render: (args) => <RuntimeWebActivationResetStory {...args} />,
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const duration = canvas.getByLabelText("Exposure duration");
    await userEvent.click(duration);
    await userEvent.click(
      within(document.body).getByRole("option", { name: "6 hours" }),
    );
    await expect(duration).toHaveValue("6 hours");
    await userEvent.click(
      canvas.getByRole("button", { name: "Refresh service observation" }),
    );
    await expect(duration).toHaveValue("24 hours");
    await userEvent.click(canvas.getByRole("button", { name: "Turn On" }));
    await expect(args.onTurnOn).toHaveBeenCalledWith(86_400);
  },
} satisfies Story;

export const TurningOn = {
  args: {
    state: {
      type: "READY",
      service: offService,
      action: "turnOn",
      actionError: null,
    },
  },
} satisfies Story;

export const AlreadyOn = {
  args: {
    state: {
      type: "READY",
      service: {
        ...offService,
        on: true,
        expires_at: "2026-09-15T09:30:00Z",
        revision: 3,
      },
      action: null,
      actionError: null,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(
        "This service is already On. Opening it does not extend its expiration.",
      ),
    ).toBeVisible();
    await expect(
      canvas.getByRole("link", { name: "Open service" }),
    ).toHaveAttribute("href", offService.url);
  },
} satisfies Story;

export const AlreadyOnDeepLink = {
  args: {
    ...AlreadyOn.args,
    applicationUrl:
      "https://preview.runtime.example.com/catalog/item?view=grid#details",
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("link", { name: "Open service" }),
    ).toHaveAttribute("href", args.applicationUrl);
  },
} satisfies Story;

export const ActionError = {
  args: {
    state: {
      type: "READY",
      service: offService,
      action: null,
      actionError: "The service changed. Reload and try again.",
    },
  },
} satisfies Story;

export const Loading = {
  args: {
    state: { type: "LOADING" },
  },
} satisfies Story;

export const Error = {
  args: {
    state: {
      type: "ERROR",
      message: "This web service is no longer available.",
    },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Try again" }));
    await expect(args.onRetry).toHaveBeenCalledOnce();
  },
} satisfies Story;
