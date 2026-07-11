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
import { IconDownload, IconMinus, IconPlus, IconX } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { type TouchEvent, useEffect, useRef, useState } from "react";
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
  const [zoom, setZoom] = useState(1);
  const pinchStart = useRef<{ distance: number; zoom: number } | null>(null);

  useEffect(() => {
    if (opened) {
      setZoom(1);
    }
  }, [opened, preview]);

  const detail = [mediaType, size == null ? null : formatFileSize(size)]
    .filter(Boolean)
    .join(" · ");
  const imageUrl =
    preview.type === "text"
      ? null
      : preview.type === "image"
        ? preview.url
        : preview.imageUrl;
  const imageAlt =
    preview.type === "text"
      ? ""
      : preview.type === "image"
        ? preview.altText
        : `${name} page ${preview.pageNumber}`;
  const touchDistance = (event: TouchEvent<HTMLDivElement>): number => {
    const first = event.touches.item(0);
    const second = event.touches.item(1);
    return Math.hypot(
      second.clientX - first.clientX,
      second.clientY - first.clientY,
    );
  };
  const startPinch = (event: TouchEvent<HTMLDivElement>): void => {
    if (event.touches.length !== 2) {
      return;
    }
    pinchStart.current = { distance: touchDistance(event), zoom };
  };
  const updatePinch = (event: TouchEvent<HTMLDivElement>): void => {
    if (event.touches.length !== 2 || pinchStart.current === null) {
      return;
    }
    event.preventDefault();
    const nextZoom =
      pinchStart.current.zoom *
      (touchDistance(event) / pinchStart.current.distance);
    setZoom(Math.min(3, Math.max(1, nextZoom)));
  };

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
        ) : (
          <Box
            bg="var(--mantine-color-dark-9)"
            onTouchStart={startPinch}
            onTouchMove={updatePinch}
            onTouchEnd={() => {
              pinchStart.current = null;
            }}
            style={{
              alignItems: "center",
              display: "flex",
              flex: 1,
              justifyContent: "center",
              minHeight: 0,
              overflow: "auto",
              padding: "var(--mantine-spacing-md)",
              position: "relative",
            }}
          >
            {previewUsesImage(preview) && (
              <img
                src={imageUrl ?? ""}
                alt={imageAlt}
                style={{
                  display: "block",
                  height: "auto",
                  margin: "auto",
                  maxHeight: zoom === 1 ? "100%" : "none",
                  maxWidth: zoom === 1 ? "100%" : "none",
                  objectFit: "contain",
                  width: zoom === 1 ? "auto" : `${zoom * 100}%`,
                }}
              />
            )}

            <Group
              gap="2xs"
              wrap="nowrap"
              bg="color-mix(in srgb, var(--mantine-color-black) 72%, transparent)"
              p="2xs"
              style={{
                borderRadius: "var(--mantine-radius-xl)",
                bottom: `max(var(--mantine-spacing-md), env(safe-area-inset-bottom))`,
                left: "50%",
                position: "absolute",
                transform: "translateX(-50%)",
              }}
            >
              <ActionIcon
                variant="transparent"
                color="white"
                disabled={zoom <= 1}
                onClick={() => setZoom((value) => Math.max(1, value - 0.25))}
                aria-label={t("zoomOut")}
              >
                <IconMinus size={18} />
              </ActionIcon>
              <Text c="white" size="xs" w={rem(44)} ta="center">
                {Math.round(zoom * 100)}%
              </Text>
              <ActionIcon
                variant="transparent"
                color="white"
                disabled={zoom >= 3}
                onClick={() => setZoom((value) => Math.min(3, value + 0.25))}
                aria-label={t("zoomIn")}
              >
                <IconPlus size={18} />
              </ActionIcon>
            </Group>
          </Box>
        )}
      </Box>
    </Modal>
  );
}
