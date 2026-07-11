import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AttachmentPreviewViewer } from "./AttachmentPreviewViewer";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const closePreview = (): void => {};

const meta = {
  component: AttachmentPreviewViewer,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof AttachmentPreviewViewer>;

export default meta;

type Story = StoryObj<typeof meta>;

export const ImagePreview = {
  args: {
    opened: true,
    onClose: closePreview,
    name: "mobile-model-picker.png",
    mediaType: "image/png",
    size: 348_707,
    downloadUrl: "/api/chat/exchange-files/story-image/download",
    preview: {
      type: "image",
      url: "/api/chat/exchange-files/story-image/download",
      altText: "Mobile model picker screenshot",
    },
  },
} satisfies Story;

export const TextPreview = {
  args: {
    opened: true,
    onClose: closePreview,
    name: "attachment-upload-test.txt",
    mediaType: "text/plain",
    size: 298,
    downloadUrl: "/api/chat/exchange-files/story-text/download",
    preview: {
      type: "text",
      text: `Azents 파일 첨부 업로드 테스트

이 파일은 텍스트 파일 다운로드 및 재업로드 동작을 확인하기 위해 생성되었습니다.

- 파일 형식: text/plain
- 인코딩: UTF-8
- 테스트 항목: 다운로드, 선택, 업로드, 첨부 버블 표시

Hello from Azents!`,
    },
  },
} satisfies Story;
