"use client";

import { Box, Button, Group, Portal, rem } from "@mantine/core";
import { IconClipboard, IconEdit } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useBrowserToolbarTouch } from "../containers/useBrowserToolbarTouch";
import type { BrowserEditorViewport } from "../containers/useBrowserEditorViewport";
import type { ReactElement } from "react";

export interface BrowserKeyboardToolbarProps {
  viewport: BrowserEditorViewport | null;
  appearance: "bar" | "floating";
  onPaste: () => void;
  onOpen: () => void;
}

/** Action buttons only: native editing remains in the separate modal. */
export function BrowserKeyboardToolbar({
  viewport,
  appearance,
  onPaste,
  onOpen,
}: BrowserKeyboardToolbarProps): ReactElement {
  const t = useTranslations("chat.browser");
  const pasteRef = useBrowserToolbarTouch(onPaste);
  const openRef = useBrowserToolbarTouch(onOpen);
  const bottom =
    viewport === null ? "100dvh" : rem(viewport.top + viewport.height);
  const floating = appearance === "floating";
  return (
    <>
      {!floating && (
        <Portal>
          <Box
            aria-hidden
            data-browser-toolbar-backdrop
            style={{
              position: "fixed",
              top: bottom,
              left: viewport === null ? 0 : rem(viewport.left),
              width: viewport === null ? "100%" : rem(viewport.width),
              height: "100lvh",
              background: "var(--mantine-color-body)",
              zIndex: "calc(var(--mantine-z-index-modal) + 1)",
              pointerEvents: "none",
            }}
          />
        </Portal>
      )}
      <Box
        data-browser-input-toolbar
        data-browser-paste
        data-appearance={appearance}
        role="toolbar"
        aria-label={t("keyboardActions")}
        style={{
          position: "fixed",
          top: floating ? `calc(${bottom} - ${rem(12)})` : bottom,
          left: viewport === null ? 0 : rem(viewport.left),
          width: viewport === null ? "100%" : rem(viewport.width),
          transform: "translateY(-100%)",
          padding: floating
            ? `0 ${rem(12)}`
            : `var(--mantine-spacing-xs) var(--mantine-spacing-sm)`,
          background: floating ? "transparent" : "var(--mantine-color-body)",
          borderTop: floating
            ? "none"
            : `${rem(1)} solid var(--mantine-color-default-border)`,
          zIndex: "calc(var(--mantine-z-index-modal) + 1)",
          pointerEvents: "none",
        }}
      >
        <Group
          justify={floating ? "flex-end" : "space-between"}
          gap="xs"
          wrap="nowrap"
          maw={rem(640)}
          mx="auto"
          style={{ pointerEvents: "auto" }}
        >
          <Button
            ref={pasteRef}
            variant={floating ? "default" : "subtle"}
            color="gray"
            radius={floating ? "xl" : "sm"}
            size={floating ? "xs" : "md"}
            leftSection={<IconClipboard size={16} aria-hidden />}
            style={{
              boxShadow: floating ? "var(--mantine-shadow-md)" : "none",
            }}
            onPointerDown={(event) => event.preventDefault()}
            onClick={onPaste}
          >
            {t("paste")}
          </Button>
          <Button
            ref={openRef}
            variant={floating ? "filled" : "light"}
            radius={floating ? "xl" : "sm"}
            size={floating ? "xs" : "md"}
            leftSection={<IconEdit size={16} aria-hidden />}
            style={{
              boxShadow: floating ? "var(--mantine-shadow-md)" : "none",
            }}
            onPointerDown={(event) => event.preventDefault()}
            onClick={onOpen}
          >
            {t("fieldEditorAction")}
          </Button>
        </Group>
      </Box>
    </>
  );
}
