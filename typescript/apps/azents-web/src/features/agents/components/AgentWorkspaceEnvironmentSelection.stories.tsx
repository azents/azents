import { rem } from "@mantine/core";
import { NextIntlClientProvider } from "next-intl";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";
import koreanMessages from "@/i18n/ko-KR-messages";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentWorkspaceEnvironmentSelection } from "./AgentWorkspaceEnvironmentSelection";
import type { AgentWorkspaceEnvironmentSelectionProps } from "./AgentWorkspaceEnvironmentSelection";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const settings = {
  entries: [
    { id: "one", name: "OPENAI_API_KEY", has_value: true },
    { id: "two", name: "NOTION_TOKEN", has_value: true },
    { id: "three", name: "DEPLOY_ENV", has_value: true },
  ],
  selected_ids: [],
  overridden_names: [],
  can_manage: true,
};
const noop = (): void => {};
const meta = {
  title: "Agents/Runtime/Workspace environment selection",
  component: AgentWorkspaceEnvironmentSelection,
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="ko-KR" messages={koreanMessages}>
        <StorybookCanvas maxWidth={rem(960)}>
          <Story />
        </StorybookCanvas>
      </NextIntlClientProvider>
    ),
  ],
  args: {
    handle: "engineering",
    state: {
      type: "READY",
      settings,
      selectedIds: [],
      dirty: false,
      saving: false,
      saved: false,
      error: null,
    },
    onToggle: noop,
    onSave: noop,
    onDiscard: noop,
    onRetry: noop,
  },
} satisfies Meta<typeof AgentWorkspaceEnvironmentSelection>;
export default meta;
type Story = StoryObj<typeof meta>;
export const DefaultNone = {} satisfies Story;
export const SelectedWithOverride = {
  args: {
    state: {
      type: "READY",
      settings: {
        ...settings,
        selected_ids: ["one", "two"],
        overridden_names: ["OPENAI_API_KEY"],
      },
      selectedIds: ["one", "two"],
      dirty: false,
      saving: false,
      saved: false,
      error: null,
    },
  },
} satisfies Story;
export const Empty = {
  args: {
    state: {
      type: "READY",
      settings: { ...settings, entries: [] },
      selectedIds: [],
      dirty: false,
      saving: false,
      saved: false,
      error: null,
    },
  },
} satisfies Story;
export const ReadOnly = {
  args: {
    state: {
      type: "READY",
      settings: { ...settings, can_manage: false },
      selectedIds: [],
      dirty: false,
      saving: false,
      saved: false,
      error: null,
    },
  },
} satisfies Story;
export const Loading = { args: { state: { type: "LOADING" } } } satisfies Story;
export const LoadError = {
  args: {
    state: { type: "ERROR", message: "Could not load Workspace variables." },
  },
} satisfies Story;
export const StaleSelectionError = {
  args: {
    state: {
      type: "READY",
      settings,
      selectedIds: ["one"],
      dirty: true,
      saving: false,
      saved: false,
      error:
        "Selected Workspace variables are unavailable. Reload the settings.",
    },
  },
} satisfies Story;

function InteractivePreview(): React.ReactElement {
  const [selected, setSelected] = useState<string[]>([]);
  const [stored, setStored] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const state: AgentWorkspaceEnvironmentSelectionProps["state"] = {
    type: "READY",
    settings,
    selectedIds: selected,
    dirty: JSON.stringify(selected) !== JSON.stringify(stored),
    saving: false,
    saved,
    error: null,
  };
  return (
    <AgentWorkspaceEnvironmentSelection
      handle="engineering"
      state={state}
      onToggle={(id, checked) => {
        setSelected(
          checked
            ? [...selected, id]
            : selected.filter((value) => value !== id),
        );
        setSaved(false);
      }}
      onSave={() => {
        setStored(selected);
        setSaved(true);
      }}
      onDiscard={() => {
        setSelected(stored);
        setSaved(false);
      }}
      onRetry={noop}
    />
  );
}
export const OptInAndDiscard = {
  render: (): React.ReactElement => <InteractivePreview />,
  play: async ({ canvasElement }): Promise<void> => {
    const canvas = within(canvasElement);
    const key = canvas.getByRole("checkbox", { name: "OPENAI_API_KEY" });
    await expect(key).not.toBeChecked();
    await expect(
      canvas.getByRole("button", { name: "변경사항 저장" }),
    ).toBeDisabled();
    await userEvent.click(key);
    await expect(key).toBeChecked();
    await userEvent.click(
      canvas.getByRole("button", { name: "변경사항 저장" }),
    );
    await expect(canvas.getByRole("status")).toHaveTextContent(
      "변경사항을 저장했습니다",
    );
    await userEvent.click(key);
    await expect(key).not.toBeChecked();
    await userEvent.click(canvas.getByRole("button", { name: "변경 취소" }));
    await expect(key).toBeChecked();
  },
} satisfies Story;
