"use client";

import {
  Box,
  Button,
  Group,
  Modal,
  rem,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useBrowserFieldEditorView } from "../containers/useBrowserFieldEditorView";
import { BrowserKeyboardToolbar } from "./BrowserKeyboardToolbar";
import type { BrowserEditorViewport } from "../containers/useBrowserEditorViewport";
import type { BrowserFieldEditorViewProps } from "../containers/useBrowserFieldEditorView";
import type { BrowserFieldAttributes } from "../types";
import type { ReactElement } from "react";

export interface BrowserFieldEditorDraft {
  label: string;
  kind: "text" | "password" | "multiline";
  attributes: BrowserFieldAttributes;
  value: string;
}

/** Pure UI for the private one-field edit flow. */
export interface BrowserFieldEditorControls {
  enabled: boolean;
  canOpen?: boolean;
  pending?: boolean;
  failed?: boolean;
  sendFailed?: boolean;
  draft: BrowserFieldEditorDraft | null;
  retainClosingDraft?: boolean;
  viewport: BrowserEditorViewport | null;
  toolbarVisible: boolean;
  toolbarAppearance: "bar" | "floating";
  onOpen: () => void;
  onChange: (value: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  onPaste: (insertNative: (text: string) => string | null) => void;
  onDirectPaste: () => void;
}

export function BrowserFieldEditorView({
  controls,
  motion,
  textRef,
  multilineRef,
  cancelRef,
  confirmRef,
  pasteRef,
  activatePaste,
}: BrowserFieldEditorViewProps): ReactElement {
  const t = useTranslations("chat.browser");
  const draft = motion.draft;
  const nativeProps =
    draft === null
      ? {}
      : {
          autoComplete: draft.attributes.autocomplete,
          autoCapitalize: draft.attributes.autocapitalize ?? "",
          autoCorrect: draft.attributes.autocorrect ?? "",
          spellCheck: draft.attributes.spellcheck,
          maxLength: Math.min(draft.attributes.max_length ?? 32768, 32768),
          ...(draft.attributes.min_length === null
            ? {}
            : { minLength: draft.attributes.min_length }),
          ...(draft.attributes.input_mode === null
            ? {}
            : { inputMode: draft.attributes.input_mode }),
          ...(draft.attributes.enter_key_hint === null
            ? {}
            : { enterKeyHint: draft.attributes.enter_key_hint }),
          name: draft.attributes.name,
          placeholder: draft.attributes.placeholder,
          required: draft.attributes.required,
        };
  const viewport = controls.viewport;
  return (
    <>
      {controls.enabled &&
        controls.toolbarVisible &&
        controls.draft === null &&
        draft === null && (
          <BrowserKeyboardToolbar
            viewport={viewport}
            appearance={controls.toolbarAppearance}
            editDisabled={controls.canOpen === false}
            onPaste={controls.onDirectPaste}
            onOpen={controls.onOpen}
          />
        )}
      <Modal.Root
        opened={controls.draft !== null}
        onClose={controls.onCancel}
        fullScreen
        closeOnClickOutside={false}
        transitionProps={{
          transition: "fade",
          duration: motion.duration,
          exitDuration: motion.exitDuration,
        }}
        onExitTransitionEnd={motion.onExited}
        zIndex="calc(var(--mantine-z-index-modal) + 2)"
        styles={{
          inner: {
            top: viewport === null ? 0 : rem(viewport.top),
            left: viewport === null ? 0 : rem(viewport.left),
            width: viewport === null ? "100%" : rem(viewport.width),
            height: viewport === null ? "100dvh" : rem(viewport.height),
            padding: 0,
          },
          content: {
            width: "100%",
            maxWidth: "100%",
            height: "100%",
            maxHeight: "100%",
            borderRadius: 0,
            boxShadow: "none",
          },
          header: {
            paddingTop:
              "max(env(safe-area-inset-top), var(--mantine-spacing-sm))",
          },
          body: {
            paddingBottom:
              "max(env(safe-area-inset-bottom), var(--mantine-spacing-lg))",
          },
        }}
      >
        <Modal.Overlay
          data-browser-field-editor-background
          color="var(--mantine-color-body)"
          backgroundOpacity={1}
        />
        <Modal.Content data-browser-field-editor>
          <Modal.Header>
            <Group justify="space-between" wrap="nowrap" w="100%">
              <Button
                ref={cancelRef}
                variant="subtle"
                color="gray"
                disabled={controls.pending}
                onPointerDown={(event) => event.preventDefault()}
                onClick={controls.onCancel}
              >
                {t("fieldEditorCancel")}
              </Button>
              <Modal.Title>
                <Text fw={600} component="span">
                  {t("fieldEditorTitle")}
                </Text>
              </Modal.Title>
              <Button
                ref={confirmRef}
                disabled={controls.pending}
                onPointerDown={(event) => event.preventDefault()}
                onClick={controls.onConfirm}
              >
                {t("fieldEditorConfirm")}
              </Button>
            </Group>
          </Modal.Header>
          <Modal.Body>
            {draft !== null && (
              <Box maw={rem(640)} mx="auto" p="md">
                <Stack gap="lg">
                  <Text size="sm">{t("fieldEditorDescription")}</Text>
                  {draft.kind === "multiline" ? (
                    <Textarea
                      {...nativeProps}
                      ref={multilineRef}
                      readOnly={controls.pending}
                      error={controls.sendFailed && t("fieldEditorSendFailed")}
                      data-autofocus
                      autoFocus
                      label={draft.label}
                      value={draft.value}
                      autosize
                      minRows={6}
                      maxRows={16}
                      size="md"
                      onChange={(event) =>
                        controls.onChange(event.currentTarget.value)
                      }
                    />
                  ) : (
                    <TextInput
                      {...nativeProps}
                      ref={textRef}
                      readOnly={controls.pending}
                      error={controls.sendFailed && t("fieldEditorSendFailed")}
                      data-autofocus
                      autoFocus
                      label={draft.label}
                      type={
                        draft.attributes.input_type === "textarea"
                          ? "text"
                          : draft.attributes.input_type
                      }
                      pattern={draft.attributes.pattern}
                      multiple={draft.attributes.multiple}
                      value={draft.value}
                      size="md"
                      onChange={(event) =>
                        controls.onChange(event.currentTarget.value)
                      }
                    />
                  )}
                  <Group>
                    <Button
                      ref={pasteRef}
                      disabled={controls.pending}
                      variant="light"
                      onPointerDown={(event) => event.preventDefault()}
                      onClick={activatePaste}
                    >
                      {t("paste")}
                    </Button>
                    <Text size="xs">{t("fieldEditorOneShot")}</Text>
                  </Group>
                </Stack>
              </Box>
            )}
          </Modal.Body>
        </Modal.Content>
      </Modal.Root>
    </>
  );
}

export const BrowserFieldEditor = createReactContainer(
  "BrowserFieldEditor",
  useBrowserFieldEditorView,
  BrowserFieldEditorView,
);
