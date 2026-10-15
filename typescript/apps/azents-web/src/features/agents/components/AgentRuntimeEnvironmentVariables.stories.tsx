import { rem, Stack, Text } from "@mantine/core";
import { NextIntlClientProvider } from "next-intl";
import { expect, userEvent, within } from "storybook/test";
import koreanMessages from "@/i18n/ko-KR-messages";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentRuntimeEnvironmentVariables } from "./AgentRuntimeEnvironmentVariables";
import {
  editingEntries,
  RuntimeEnvironmentPreview,
  storedEntries,
} from "./AgentRuntimeEnvironmentVariables.story-fixtures";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};

const meta = {
  title: "Agents/Runtime/Environment variables",
  component: AgentRuntimeEnvironmentVariables,
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="ko-KR" messages={koreanMessages}>
        <StorybookCanvas maxWidth={rem(960)}>
          <Stack gap="sm">
            <Text size="xs" c="dimmed">
              UI 미리보기 · 샘플 데이터 · 변경사항은 실제로 저장되지 않습니다
            </Text>
            <Story />
          </Stack>
        </StorybookCanvas>
      </NextIntlClientProvider>
    ),
  ],
  args: {
    state: {
      type: "READY",
      entries: storedEntries,
      canManage: true,
      status: { type: "UNCHANGED" },
    },
    onAdd: noop,
    onNameChange: noop,
    onValueChange: noop,
    onRemove: noop,
    onDiscard: noop,
    onSave: noop,
    onRetry: noop,
  },
} satisfies Meta<typeof AgentRuntimeEnvironmentVariables>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WorkspaceCatalog = {
  args: { scope: "workspace" },
} satisfies Story;

export const DeleteInputAlignment = {
  play: async ({ canvasElement }): Promise<void> => {
    const canvas = within(canvasElement);
    const input = canvas
      .getByRole("textbox", { name: "변수명: OPENAI_API_KEY" })
      .getBoundingClientRect();
    const remove = canvas
      .getByRole("button", { name: "OPENAI_API_KEY 삭제" })
      .getBoundingClientRect();
    await expect(
      Math.abs(input.top + input.height / 2 - remove.top - remove.height / 2),
    ).toBeLessThan(1);
  },
} satisfies Story;

export const Registered = {
  render: (): React.ReactElement => <RuntimeEnvironmentPreview />,
} satisfies Story;

export const Editing = {
  render: (): React.ReactElement => (
    <RuntimeEnvironmentPreview initialEntries={editingEntries} initiallyDirty />
  ),
} satisfies Story;

export const Empty = {
  render: (): React.ReactElement => (
    <RuntimeEnvironmentPreview initialEntries={[]} />
  ),
} satisfies Story;

export const Loading = { args: { state: { type: "LOADING" } } } satisfies Story;
export const LoadError = {
  args: {
    state: {
      type: "ERROR",
      message: "환경변수를 불러오지 못했습니다. 다시 시도하세요.",
    },
  },
} satisfies Story;
export const ReadOnly = {
  args: {
    state: {
      type: "READY",
      entries: storedEntries,
      canManage: false,
      status: { type: "UNCHANGED" },
    },
  },
} satisfies Story;
export const Saving = {
  args: {
    state: {
      type: "READY",
      entries: editingEntries,
      canManage: true,
      status: { type: "SAVING" },
    },
  },
} satisfies Story;
export const SaveError = {
  args: {
    state: {
      type: "READY",
      entries: editingEntries,
      canManage: true,
      status: {
        type: "ERROR",
        message: "저장하지 못했습니다. 변경사항을 확인하고 다시 시도하세요.",
      },
    },
  },
} satisfies Story;

export const AddAndSave = {
  render: (): React.ReactElement => (
    <RuntimeEnvironmentPreview initialEntries={[]} />
  ),
  play: async ({ canvasElement }): Promise<void> => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "환경변수 추가" }),
    );
    await expect(
      canvas.getByRole("button", { name: "변경사항 저장" }),
    ).toBeDisabled();
    await userEvent.type(
      canvas.getByRole("textbox", { name: "변수명: 새 변수" }),
      "API_TOKEN",
    );
    await userEvent.type(
      canvas.getByLabelText("변수 값: API_TOKEN"),
      "sample-not-a-secret",
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "변경사항 저장" }),
    );
    await expect(canvas.getByRole("status")).toHaveTextContent(
      "변경사항을 저장했습니다",
    );
    await expect(canvas.getByLabelText("변수 값: API_TOKEN")).toHaveValue("");
  },
} satisfies Story;

export const DuplicateAndDiscard = {
  render: (): React.ReactElement => <RuntimeEnvironmentPreview />,
  play: async ({ canvasElement }): Promise<void> => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "환경변수 추가" }),
    );
    await userEvent.type(
      canvas.getByRole("textbox", { name: "변수명: 새 변수" }),
      "OPENAI_API_KEY",
    );
    await expect(
      canvas.getAllByText("동일한 변수명을 사용할 수 없습니다."),
    ).toHaveLength(2);
    await expect(
      canvas.getByRole("button", { name: "변경사항 저장" }),
    ).toBeDisabled();
    await userEvent.click(canvas.getByRole("button", { name: "변경 취소" }));
    await expect(
      canvas.getAllByRole("textbox", { name: /^변수명:/ }),
    ).toHaveLength(3);
    await expect(canvas.getByRole("status")).toHaveTextContent(
      "환경변수 3개 등록됨",
    );
  },
} satisfies Story;

export const RemoveAndDiscard = {
  render: (): React.ReactElement => <RuntimeEnvironmentPreview />,
  play: async ({ canvasElement }): Promise<void> => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "NOTION_TOKEN 삭제" }),
    );
    await expect(
      canvas.queryByRole("textbox", { name: "변수명: NOTION_TOKEN" }),
    ).not.toBeInTheDocument();
    await expect(canvas.getByRole("status")).toHaveTextContent(
      "저장하지 않은 변경사항",
    );
    await userEvent.click(canvas.getByRole("button", { name: "변경 취소" }));
    await expect(
      canvas.getByRole("textbox", { name: "변수명: NOTION_TOKEN" }),
    ).toBeInTheDocument();
  },
} satisfies Story;
