/* eslint-disable @next/next/no-img-element -- Exchange previews use dynamic proxy URLs */
"use client";

import {
  ActionIcon,
  Box,
  Button,
  Code,
  Group,
  Modal,
  rem,
  ScrollArea,
  Text,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { IconDownload, IconFile, IconX } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { formatFileSize } from "./FileAttachmentList";

export type AttachmentPreviewContent =
  | {
      type: "image";
      url: string;
      altText: string;
    }
  | {
      type: "text";
      text: string;
    }
  | {
      type: "document-page";
      imageUrl: string;
      pageNumber: number;
    }
  | {
      type: "unsupported";
    };

interface AttachmentPreviewViewerProps {
  opened: boolean;
  onClose: () => void;
  name: string;
  mediaType: string;
  size?: number;
  downloadUrl: string;
  preview: AttachmentPreviewContent;
}

function inlinePreviewUrl(url: string): string {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}disposition=inline`;
}

function previewUsesImage(
  preview: AttachmentPreviewContent,
): preview is Extract<
  AttachmentPreviewContent,
  { type: "image" | "document-page" }
> {
  return preview.type === "image" || preview.type === "document-page";
}

export function AttachmentPreviewViewer({
  opened,
  onClose,
  name,
  mediaType,
  size,
  downloadUrl,
  preview,
}: AttachmentPreviewViewerProps): React.ReactElement {
  const t = useTranslations("chat.attachment");
  const isMobile = useMediaQuery("(max-width: 48em)");

  const detail = [mediaType, size == null ? null : formatFileSize(size)]
    .filter(Boolean)
    .join(" · ");
  const imageUrl =
    preview.type === "image"
      ? preview.url
      : preview.type === "document-page"
        ? preview.imageUrl
        : null;
  const imageAlt =
    preview.type === "image"
      ? preview.altText
      : preview.type === "document-page"
        ? `${name} page ${preview.pageNumber}`
        : "";
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      fullScreen={isMobile}
      size="xl"
      centered
      padding={0}
      withCloseButton={false}
      closeOnClickOutside={false}
      styles={{
        body: { height: "100%", padding: 0 },
        content: {
          height: isMobile ? "100dvh" : "min(85dvh, 60rem)",
          overflow: "hidden",
        },
      }}
    >
      <Box
        style={{
          display: "flex",
          flexDirection: "column",
          height: "100%",
          minHeight: 0,
        }}
      >
        <Group
          component="header"
          gap="sm"
          px="md"
          py="sm"
          wrap="nowrap"
          style={{
            borderBottom: `${rem(1)} solid var(--mantine-color-default-border)`,
            flex: "0 0 auto",
            paddingTop: `max(var(--mantine-spacing-sm), env(safe-area-inset-top))`,
          }}
        >
          <ActionIcon
            variant="subtle"
            color="gray"
            size="lg"
            onClick={onClose}
            aria-label={t("closePreview")}
          >
            <IconX size={22} />
          </ActionIcon>

          <Box style={{ flex: 1, minWidth: 0 }}>
            <Text size="sm" fw={600} truncate>
              {name}
            </Text>
            <Text size="xs" c="dimmed" truncate>
              {detail}
            </Text>
          </Box>

          <Button
            component="a"
            href={downloadUrl}
            download={name}
            variant="light"
            size="compact-sm"
            leftSection={<IconDownload size={16} />}
          >
            {t("download")}
          </Button>
        </Group>

        {preview.type === "text" ? (
          <ScrollArea style={{ flex: 1, minHeight: 0 }}>
            <Box p="md">
              <Code
                block
                style={{
                  fontSize: rem(14),
                  lineHeight: 1.6,
                  minHeight: "calc(100dvh - 8rem)",
                  padding: "var(--mantine-spacing-md)",
                  whiteSpace: "pre-wrap",
                }}
              >
                {preview.text}
              </Code>
            </Box>
          </ScrollArea>
        ) : preview.type === "unsupported" ? (
          <Box
            style={{
              alignItems: "center",
              display: "flex",
              flex: 1,
              flexDirection: "column",
              gap: "var(--mantine-spacing-sm)",
              justifyContent: "center",
              minHeight: 0,
              padding: "var(--mantine-spacing-xl)",
              textAlign: "center",
            }}
          >
            <IconFile size={48} color="var(--mantine-color-dimmed)" />
            <Text fw={600}>{t("previewUnavailable")}</Text>
            <Text size="sm" c="dimmed">
              {t("downloadToOpen")}
            </Text>
          </Box>
        ) : (
          <Box
            bg="var(--mantine-color-dark-9)"
            style={{
              alignItems: "center",
              display: "flex",
              flex: 1,
              justifyContent: "center",
              minHeight: 0,
              overflow: "hidden",
              padding: "var(--mantine-spacing-md)",
            }}
          >
            {previewUsesImage(preview) && imageUrl !== null ? (
              <a
                href={inlinePreviewUrl(imageUrl)}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t("openOriginal")}
                style={{
                  alignItems: "center",
                  display: "flex",
                  height: "100%",
                  justifyContent: "center",
                  minHeight: 0,
                  width: "100%",
                }}
              >
                <img
                  src={imageUrl}
                  alt={imageAlt}
                  style={{
                    cursor: "zoom-in",
                    display: "block",
                    height: "auto",
                    maxHeight: "100%",
                    maxWidth: "100%",
                    objectFit: "contain",
                    width: "auto",
                  }}
                />
              </a>
            ) : null}
          </Box>
        )}
      </Box>
    </Modal>
  );
}
