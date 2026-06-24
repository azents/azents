import type { PendingFile } from "./hooks/useFileUpload";
import type { ActiveToolCall, ChatMessage, FileAttachment } from "./types";

const now = new Date("2026-05-01T10:00:00.000Z").toISOString();

export const storySessionId = "story-session-001";

export const imageAttachment: FileAttachment = {
  attachmentId: "story-image",
  uri: "exchange://exchange/story/files/image/original",
  mediaType: "image/jpeg",
  size: 184320,
  name: "dashboard.jpg",
  previewThumbnailUri: "exchange://exchange/story/files/image/preview.jpg",
};

export const textAttachment: FileAttachment = {
  attachmentId: "story-text",
  uri: "exchange://exchange/story/files/text/original",
  mediaType: "text/plain",
  size: 2048,
  name: "run-output.txt",
  textPreview:
    "Build completed successfully.\nLint warnings: 0\nTests: 42 passed",
};

export const binaryAttachment: FileAttachment = {
  attachmentId: "story-binary",
  uri: "exchange://exchange/story/files/binary/original",
  mediaType: "application/zip",
  size: 7340032,
  name: "result.zip",
};

export const expiredAttachment: FileAttachment = {
  attachmentId: "story-expired",
  uri: "exchange://exchange/story/files/expired/original",
  mediaType: "image/jpeg",
  size: 512000,
  name: "expired-screenshot.jpg",
  previewThumbnailUri: "exchange://exchange/story/files/expired/preview.jpg",
  availability: "expired",
};

export const unavailableAttachment: FileAttachment = {
  attachmentId: "story-missing",
  uri: "exchange://exchange/story/files/missing/original",
  mediaType: "application/pdf",
  size: 128000,
  name: "missing-report.pdf",
  availability: "unavailable",
};

export const unsupportedUriAttachment: FileAttachment = {
  uri: "file:///workspace/agent/result.log",
  mediaType: "text/plain",
  size: 4096,
  name: "legacy-result.log",
  textPreview: "Legacy file URI attachment should render without crashing.",
};

export const runningToolCall: ActiveToolCall = {
  id: "tool-call-running",
  name: "shell.exec",
  arguments: JSON.stringify({ command: "pnpm run build" }),
  status: "running",
};

export const preparingToolCall: ActiveToolCall = {
  id: "tool-call-preparing",
  name: "",
  arguments: JSON.stringify({ command: "pnpm run build" }),
  status: "preparing",
};

export const completedToolCall: ActiveToolCall = {
  id: "tool-call-completed",
  name: "github.create_pull_request",
  arguments: JSON.stringify({ title: "Add Storybook", base: "main" }),
  result: JSON.stringify({
    url: "https://github.com/azents/azents/pull/3209",
  }),
  status: "completed",
};

export const failedToolCall: ActiveToolCall = {
  id: "tool-call-failed",
  name: "bash",
  arguments: JSON.stringify({ command: "pnpm run build" }),
  result: "Runner operation route unavailable: subject-1",
  status: "failed",
};

export const interruptedToolCall: ActiveToolCall = {
  id: "tool-call-interrupted",
  name: "bash",
  arguments: JSON.stringify({ command: "sleep 120" }),
  result: "Tool execution was interrupted by user stop.",
  status: "interrupted",
};

export const attachmentToolCall: ActiveToolCall = {
  id: "tool-call-attachments",
  name: "browser.screenshot",
  arguments: "{ malformed json still renders }",
  result: JSON.stringify({ saved: true }),
  status: "completed",
  attachments: [imageAttachment, textAttachment],
};

export function createChatMessage(
  overrides: Partial<ChatMessage>,
): ChatMessage {
  return {
    id: "message-base",
    role: "assistant",
    content: "Hello from azents.",
    createdAt: now,
    status: "complete",
    ...overrides,
  };
}

function createFile(name: string, type: string, content: string): File {
  return new File([content], name, { type });
}

export const pendingFiles: PendingFile[] = [
  {
    id: "pending-image",
    file: createFile("screenshot.png", "image/png", "image-bytes"),
    status: "pending",
  },
  {
    id: "uploading-log",
    file: createFile("server.log", "text/plain", "log line"),
    status: "uploading",
  },
  {
    id: "done-report",
    file: createFile("report.pdf", "application/pdf", "pdf-bytes"),
    status: "done",
  },
  {
    id: "error-archive",
    file: createFile("archive.zip", "application/zip", "zip-bytes"),
    status: "error",
    errorReason: "unsupportedType",
    errorDetail: "Unsupported file format.",
    errorRetryable: false,
  },
];

export const markdownSample = `# Agent result

The run finished with **three** notable outcomes:

- Created a reusable Storybook provider
- Added isolated chat UI states
- Left backend calls out of the stories

\`pnpm run build-storybook\` should pass before publishing.

| State | Result |
| --- | --- |
| Loading | visible |
| Error | visible |
| Complete | visible |
`;

export const codeReadabilityMarkdownSample = `Inline code should stay readable: \`const threshold = Math.floor(maxInput * 0.9)\`.

\`\`\`ts
export function getCompactionThreshold(maxInput: number): number {
  const threshold = Math.floor(maxInput * 0.9);
  return threshold;
}
\`\`\`

\`\`\`json
{
  "theme": "light",
  "readability": true,
  "tokens": ["inline", "block"]
}
\`\`\`

\`\`\`
pnpm --filter @azents/web typecheck
\`\`\`
`;
