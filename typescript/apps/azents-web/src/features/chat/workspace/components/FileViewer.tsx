"use client";

/* eslint-disable @next/next/no-img-element -- workspace image is dynamically served through authenticated proxy URL, so not target for next/image optimization */
/** Workspace file preview component. */
import {
  Box,
  Button,
  Code,
  Group,
  Loader,
  Paper,
  rem,
  ScrollArea,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import {
  IconArrowLeft,
  IconDownload,
  IconFileText,
  IconPhoto,
  IconTable,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { WorkspaceFile, WorkspaceFileState } from "../types";

interface FileViewerProps {
  state: WorkspaceFileState;
  getDownloadHref: (path: string) => string;
  onBack?: () => void;
}

function getFileName(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type WorkspacePreviewKind =
  | "CSV"
  | "IMAGE"
  | "JSON"
  | "MARKDOWN"
  | "PDF"
  | "TEXT"
  | "UNSUPPORTED";

function hasExtension(path: string, extensions: readonly string[]): boolean {
  const lowerPath = path.toLowerCase();
  return extensions.some((extension) => lowerPath.endsWith(extension));
}

function getPreviewKind(
  path: string,
  mediaType: string,
  text: string | null,
): WorkspacePreviewKind {
  const lowerMediaType = mediaType.toLowerCase();

  if (lowerMediaType.startsWith("image/")) {
    return "IMAGE";
  }
  if (lowerMediaType === "application/pdf" || hasExtension(path, [".pdf"])) {
    return "PDF";
  }
  if (
    lowerMediaType === "text/markdown" ||
    hasExtension(path, [".md", ".markdown", ".mdx"])
  ) {
    return text === null ? "UNSUPPORTED" : "MARKDOWN";
  }
  if (
    lowerMediaType === "application/json" ||
    lowerMediaType.endsWith("+json") ||
    hasExtension(path, [".json", ".jsonc"])
  ) {
    return text === null ? "UNSUPPORTED" : "JSON";
  }
  if (lowerMediaType === "text/csv" || hasExtension(path, [".csv"])) {
    return text === null ? "UNSUPPORTED" : "CSV";
  }
  if (text !== null) {
    return "TEXT";
  }
  return "UNSUPPORTED";
}

function formatJson(rawText: string): { error: boolean; text: string } {
  try {
    const parsed: unknown = JSON.parse(rawText);
    return { error: false, text: JSON.stringify(parsed, null, 2) };
  } catch (error) {
    if (error instanceof SyntaxError) {
      return { error: true, text: rawText };
    }
    throw error;
  }
}

function parseCsvRows(rawText: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < rawText.length; index += 1) {
    const char = rawText.charAt(index);
    const nextChar = rawText.charAt(index + 1);

    if (char === '"') {
      if (quoted && nextChar === '"') {
        cell += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
      continue;
    }

    if (char === "," && !quoted) {
      row.push(cell);
      cell = "";
      continue;
    }

    if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && nextChar === "\n") {
        index += 1;
      }
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      continue;
    }

    cell += char;
  }

  row.push(cell);
  rows.push(row);

  return rows.filter(
    (currentRow) =>
      currentRow.length > 1 || (currentRow[0] != null && currentRow[0] !== ""),
  );
}

function CodePreview({ text }: { text: string }): React.ReactElement {
  return (
    <Box
      p="sm"
      style={{
        borderRadius: "var(--mantine-radius-sm)",
        background: "var(--mantine-color-default-hover)",
      }}
    >
      <Code block>{text}</Code>
    </Box>
  );
}

function MarkdownPreview({ text }: { text: string }): React.ReactElement {
  return (
    <Paper withBorder p="md" radius="md">
      <Box
        className="workspace-markdown-preview"
        style={{
          lineHeight: 1.6,
        }}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </Box>
    </Paper>
  );
}

function CsvPreview({ text }: { text: string }): React.ReactElement {
  const rows = parseCsvRows(text);
  const visibleRows = rows.slice(0, 60);
  const columnCount = Math.max(...visibleRows.map((row) => row.length), 0);

  if (visibleRows.length === 0 || columnCount === 0) {
    return <CodePreview text={text} />;
  }

  return (
    <Paper withBorder radius="md">
      <ScrollArea>
        <Table striped highlightOnHover withColumnBorders>
          <Table.Tbody>
            {visibleRows.map((row, rowIndex) => (
              <Table.Tr key={`${rowIndex}-${row.join("|")}`}>
                {Array.from({ length: columnCount }, (_, columnIndex) => (
                  <Table.Td key={columnIndex}>
                    <Text size="sm">{row[columnIndex] ?? ""}</Text>
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
    </Paper>
  );
}

export function FileViewer({
  state,
  getDownloadHref,
  onBack,
}: FileViewerProps): React.ReactElement {
  const t = useTranslations("chat.workspacePanel");

  function renderLoadedContent(file: WorkspaceFile): React.ReactElement {
    const previewKind = getPreviewKind(file.path, file.mediaType, file.text);
    const text = file.text;

    switch (previewKind) {
      case "IMAGE":
        return (
          <Stack align="center" justify="center" gap="sm" h="100%">
            <IconPhoto size="1.25rem" color="var(--mantine-color-dimmed)" />
            <Box
              component="figure"
              m={0}
              style={{
                maxHeight: "100%",
                maxWidth: "100%",
              }}
            >
              <img
                src={getDownloadHref(file.path)}
                alt={getFileName(file.path)}
                style={{
                  borderRadius: "var(--mantine-radius-md)",
                  maxHeight: rem(420),
                  maxWidth: "100%",
                  objectFit: "contain",
                }}
              />
            </Box>
          </Stack>
        );
      case "PDF":
        return (
          <Text size="sm" c="dimmed">
            {t("pdfPreviewUnavailable")}
          </Text>
        );
      case "MARKDOWN":
        if (text === null) {
          return (
            <Text size="sm" c="dimmed">
              {t("binaryPreviewUnavailable")}
            </Text>
          );
        }
        return <MarkdownPreview text={text} />;
      case "JSON": {
        if (text === null) {
          return (
            <Text size="sm" c="dimmed">
              {t("binaryPreviewUnavailable")}
            </Text>
          );
        }
        const formatted = formatJson(text);
        return (
          <Stack gap="xs">
            {formatted.error && (
              <Text size="xs" c="dimmed">
                {t("jsonPreviewInvalid")}
              </Text>
            )}
            <CodePreview text={formatted.text} />
          </Stack>
        );
      }
      case "CSV":
        if (text === null) {
          return (
            <Text size="sm" c="dimmed">
              {t("binaryPreviewUnavailable")}
            </Text>
          );
        }
        return (
          <Stack gap="xs">
            <Group gap="xs">
              <IconTable size="1rem" />
              <Text size="xs" c="dimmed">
                {t("csvPreview")}
              </Text>
            </Group>
            <CsvPreview text={text} />
          </Stack>
        );
      case "TEXT":
        if (text === null) {
          return (
            <Text size="sm" c="dimmed">
              {t("binaryPreviewUnavailable")}
            </Text>
          );
        }
        return <CodePreview text={text} />;
      case "UNSUPPORTED":
        return (
          <Text size="sm" c="dimmed">
            {t("binaryPreviewUnavailable")}
          </Text>
        );
    }
  }

  switch (state.type) {
    case "IDLE":
      return (
        <Stack align="center" justify="center" h="100%" gap="sm" p="md">
          <IconFileText size="1.25rem" color="var(--mantine-color-dimmed)" />
          <Text size="sm" c="dimmed" ta="center">
            {t("selectFile")}
          </Text>
        </Stack>
      );
    case "LOADING":
      return (
        <Stack align="center" justify="center" h="100%" gap="sm" p="md">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            {t("loadingFile")}
          </Text>
        </Stack>
      );
    case "ERROR":
      return (
        <Stack justify="center" h="100%" gap="sm" p="md">
          <Text size="sm" c="red">
            {state.message}
          </Text>
        </Stack>
      );
    case "LOADED": {
      const file = state.file;
      return (
        <Stack gap="sm" h="100%">
          <Group justify="space-between" gap="xs" wrap="nowrap">
            <Group gap="xs" wrap="nowrap" miw={0}>
              {onBack && (
                <Button
                  size="xs"
                  variant="subtle"
                  leftSection={<IconArrowLeft size="1rem" />}
                  onClick={onBack}
                >
                  {t("backToBrowser")}
                </Button>
              )}
              <Stack gap={0} miw={0}>
                <Text size="sm" fw={600} truncate>
                  {getFileName(file.path)}
                </Text>
                <Text size="xs" c="dimmed" truncate>
                  {file.path}
                </Text>
                <Text size="xs" c="dimmed">
                  {file.mediaType} · {formatFileSize(file.size)}
                </Text>
              </Stack>
            </Group>
            <Button
              component="a"
              href={getDownloadHref(file.path)}
              size="xs"
              variant="light"
              leftSection={<IconDownload size="1rem" />}
            >
              {t("download")}
            </Button>
          </Group>
          <ScrollArea flex={1}>
            {renderLoadedContent(file)}
            {file.truncated && (
              <Text size="xs" c="dimmed" mt="xs">
                {t("previewTruncated")}
              </Text>
            )}
          </ScrollArea>
        </Stack>
      );
    }
  }
}
