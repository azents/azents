import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentBrowserChoice } from "./AgentBrowserChoice";
import type { BrowserChoiceState } from "../browserChoiceTypes";
import type { AgentBrowserConfiguration } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const configuration: AgentBrowserConfiguration = {
  agent_id: "agent-1",
  intent_id: "0123456789abcdef0123456789abcdef",
  requested: "patchright",
  applied: "patchright",
  state: "ready",
  reason_code: null,
  runtime_id: "runtime-1",
  runner_generation: 7,
};

function ready(
  overrides: Partial<Extract<BrowserChoiceState, { type: "READY" }>>,
): BrowserChoiceState {
  return {
    type: "READY",
    configuration,
    browserEnabled: true,
    readOnly: false,
    saving: false,
    confirmation: null,
    error: null,
    ...overrides,
  };
}

const meta = {
  title: "Agents/BrowserChoice",
  tags: ["ci-contract"],
  component: AgentBrowserChoice,
  decorators: [
    (Story): React.ReactElement => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    state: ready({}),
    onSelect: fn(),
    onCancel: fn(),
    onConfirm: fn(),
    onRetry: fn(),
    onRefresh: fn(),
  },
} satisfies Meta<typeof AgentBrowserChoice>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  play: async ({ canvasElement, args }): Promise<void> => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("combobox", { name: "Browser engine" }),
    );
    await userEvent.click(
      within(canvasElement.ownerDocument.body).getByRole("option", {
        name: "Camoufox (experimental)",
      }),
    );
    await expect(args.onSelect).toHaveBeenCalledWith("camoufox");
    await expect(args.onConfirm).not.toHaveBeenCalled();
  },
};

export const ConfirmCamoufox: Story = {
  args: { state: ready({ confirmation: "camoufox" }) },
  play: async ({ canvasElement, args }): Promise<void> => {
    const body = within(canvasElement.ownerDocument.body);
    const dialog = within(await body.findByRole("dialog"));
    await expect(
      dialog.getByText(/Terminals and unrelated Runtime jobs will continue/),
    ).toBeVisible();
    await expect(
      dialog.getByText(/Each engine keeps its own saved sign-ins/),
    ).toBeVisible();
    await userEvent.click(
      dialog.getByRole("button", { name: "Apply browser choice" }),
    );
    await expect(args.onConfirm).toHaveBeenCalledOnce();
  },
};

export const CancelChange: Story = {
  args: { state: ready({ confirmation: "camoufox" }) },
  play: async ({ canvasElement, args }): Promise<void> => {
    const dialog = within(
      await within(canvasElement.ownerDocument.body).findByRole("dialog"),
    );
    await userEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    await expect(args.onCancel).toHaveBeenCalledOnce();
    await expect(args.onConfirm).not.toHaveBeenCalled();
  },
};

export const Applying: Story = {
  args: {
    state: ready({
      configuration: {
        ...configuration,
        requested: "camoufox",
        applied: null,
        state: "applying",
      },
    }),
  },
};
export const Saving: Story = {
  args: { state: ready({ confirmation: "camoufox", saving: true }) },
};
export const Offline: Story = {
  args: {
    state: ready({
      configuration: {
        ...configuration,
        requested: "camoufox",
        applied: null,
        state: "offline",
        runtime_id: null,
        runner_generation: null,
      },
    }),
  },
};
export const Failed: Story = {
  args: {
    state: ready({
      configuration: {
        ...configuration,
        requested: "camoufox",
        applied: null,
        state: "failed",
        reason_code: "browser_unavailable",
      },
    }),
  },
  play: async ({ canvasElement, args }): Promise<void> => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Retry switch" }));
    await expect(args.onRetry).toHaveBeenCalledOnce();
    await expect(args.onConfirm).not.toHaveBeenCalled();
  },
};
export const ReadOnly: Story = {
  args: { state: ready({ readOnly: true, confirmation: "camoufox" }) },
  play: async ({ canvasElement }): Promise<void> => {
    await expect(
      within(canvasElement).getByRole("combobox", { name: "Browser engine" }),
    ).toBeDisabled();
    await expect(
      within(canvasElement.ownerDocument.body).queryByRole("dialog"),
    ).not.toBeInTheDocument();
  },
};
export const BrowserDisabled: Story = {
  args: { state: ready({ browserEnabled: false }) },
  play: async ({ canvasElement, args }): Promise<void> => {
    const canvas = within(canvasElement);
    const select = canvas.getByRole("combobox", { name: "Browser engine" });
    await expect(select).toBeDisabled();
    await expect(select).toHaveValue("Patchright (default)");
    await userEvent.click(select);
    await expect(
      within(canvasElement.ownerDocument.body).queryByRole("option"),
    ).not.toBeInTheDocument();
    await expect(args.onSelect).not.toHaveBeenCalled();
  },
};
export const BrowserDisabledWithStaleFailure: Story = {
  args: {
    state: ready({
      browserEnabled: false,
      confirmation: "camoufox",
      error: "Browser settings changed elsewhere. Refresh and retry.",
      configuration: {
        ...configuration,
        state: "failed",
        reason_code: "browser_configuration_unsupported",
      },
    }),
  },
  play: async ({ canvasElement, args }): Promise<void> => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("combobox", { name: "Browser engine" }),
    ).toBeDisabled();
    await expect(canvas.queryByRole("alert")).not.toBeInTheDocument();
    await expect(
      canvas.queryByRole("button", { name: "Retry switch" }),
    ).not.toBeInTheDocument();
    await expect(
      within(canvasElement.ownerDocument.body).queryByRole("dialog"),
    ).not.toBeInTheDocument();
    await expect(args.onRetry).not.toHaveBeenCalled();
    await expect(args.onConfirm).not.toHaveBeenCalled();
  },
};
export const BrowserDisabledWhileApplying: Story = {
  args: {
    state: ready({
      browserEnabled: false,
      saving: true,
      configuration: { ...configuration, state: "applying" },
    }),
  },
  play: async ({ canvasElement }): Promise<void> => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("combobox", { name: "Browser engine" }),
    ).toBeDisabled();
    await expect(canvas.queryByRole("status")).not.toBeInTheDocument();
  },
};
export const StaleMutation: Story = {
  args: {
    state: ready({
      configuration: {
        ...configuration,
        requested: "camoufox",
        applied: "camoufox",
      },
      error: "Browser settings changed elsewhere. Refresh and retry.",
    }),
  },
};
export const Loading: Story = { args: { state: { type: "LOADING" } } };
export const LoadFailure: Story = {
  args: { state: { type: "ERROR", message: "Browser settings unavailable" } },
};
