"use client";

import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  Menu,
  rem,
  Stack,
  Text,
  TextInput,
  Tooltip,
  VisuallyHidden,
} from "@mantine/core";
import {
  IconArrowLeft,
  IconArrowRight,
  IconDots,
  IconRefresh,
  IconReload,
  IconWorld,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { browserFrameMatchesStatus, sameBrowserTarget } from "../input";
import classes from "./SessionBrowserPanel.module.css";
import type {
  BrowserImage,
  BrowserNavigationAction,
  BrowserTarget,
  BrowserViewState,
} from "../types";
import type {
  CompositionEventHandler,
  FocusEventHandler,
  FormEventHandler,
  KeyboardEventHandler,
  MouseEventHandler,
  PointerEventHandler,
  ReactElement,
  RefObject,
  WheelEventHandler,
} from "react";

export interface BrowserInteractionHandlers {
  onContextMenu: MouseEventHandler<HTMLDivElement>;
  onPointerDown: PointerEventHandler<HTMLDivElement>;
  onPointerMove: PointerEventHandler<HTMLDivElement>;
  onPointerUp: PointerEventHandler<HTMLDivElement>;
  onPointerCancel: PointerEventHandler<HTMLDivElement>;
  onLostPointerCapture: PointerEventHandler<HTMLDivElement>;
  onKeyDown: KeyboardEventHandler<HTMLElement>;
  onKeyUp: KeyboardEventHandler<HTMLElement>;
  onWheel: WheelEventHandler<HTMLDivElement>;
  onBlur: FocusEventHandler<HTMLElement>;
  onCompositionStart: CompositionEventHandler<HTMLTextAreaElement>;
  onCompositionEnd: CompositionEventHandler<HTMLTextAreaElement>;
  onKeyboardInput: FormEventHandler<HTMLTextAreaElement>;
  onSendTab: (reverse: boolean) => void;
}

export interface SessionBrowserPanelProps {
  state: BrowserViewState;
  closeError: boolean;
  onSelect: (target: BrowserTarget) => void;
  onClosePage: () => void;
  onRetry: () => void;
  onFrameDisplayed: (image: BrowserImage) => void;
  onFrameError: (image: BrowserImage) => void;
  onDialogResponse: (accept: boolean) => void;
  dialogText: string;
  onDialogTextChange: (text: string) => void;
  keyboardRef: RefObject<HTMLTextAreaElement | null> | null;
  interaction: BrowserInteractionHandlers | null;
  addressValue: string;
  addressError: boolean;
  navigationEnabled: boolean;
  onAddressChange: (value: string) => void;
  onAddressFocus: () => void;
  onAddressBlur: () => void;
  onAddressSubmit: () => void;
  onNavigate: (action: BrowserNavigationAction) => void;
}

export function SessionBrowserPanel({
  state,
  closeError,
  onSelect,
  onClosePage,
  onRetry,
  onFrameDisplayed,
  onFrameError,
  onDialogResponse,
  dialogText,
  onDialogTextChange,
  keyboardRef,
  interaction,
  addressValue,
  addressError,
  navigationEnabled,
  onAddressChange,
  onAddressFocus,
  onAddressBlur,
  onAddressSubmit,
  onNavigate,
}: SessionBrowserPanelProps): ReactElement {
  const t = useTranslations("chat.browser");
  const descriptionId = useId();
  if (state.type === "LOADING") {
    return (
      <Stack align="center" justify="center" h="100%" p="md">
        <Loader />
        <Text role="status">{t("loading")}</Text>
      </Stack>
    );
  }
  if (
    state.type === "ERROR" ||
    state.type === "UNAVAILABLE" ||
    state.type === "ACCESS_CHANGED"
  ) {
    return (
      <Stack p="md">
        <Alert
          color="yellow"
          title={
            <Text component="span" c="var(--mantine-color-text)" fw={600}>
              {state.type === "ACCESS_CHANGED"
                ? t("accessChanged")
                : t("unavailable")}
            </Text>
          }
        >
          <Text>
            {state.type === "UNAVAILABLE"
              ? state.reason
              : state.type === "ACCESS_CHANGED"
                ? t("accessChangedDescription")
                : t("loadError")}
          </Text>
        </Alert>
        <Button variant="default" onClick={onRetry}>
          {t("retry")}
        </Button>
      </Stack>
    );
  }
  if (state.type === "EMPTY") {
    return (
      <Stack p="md">
        <Text fw={600}>{t("emptyTitle")}</Text>
        <Text size="sm">{t("emptyDescription")}</Text>
        <Button variant="default" onClick={onRetry}>
          {t("refresh")}
        </Button>
      </Stack>
    );
  }
  const pages = state.pages;
  const selected = state.type === "READY" ? state.selected : null;
  const connected = state.type === "READY" && state.connection === "connected";
  const status = state.type === "READY" ? state.status : null;
  const dialogEnabled =
    state.type === "READY" &&
    connected &&
    state.canInput &&
    status?.state === "connected" &&
    status.allow_input &&
    sameBrowserTarget(status.target, state.selected.target) &&
    status.dialog !== null &&
    status.dialog.id === state.dialog?.id;
  const inputEnabled =
    state.type === "READY" &&
    connected &&
    state.canInput &&
    state.image !== null &&
    status !== null &&
    status.allow_input &&
    sameBrowserTarget(status.target, state.selected.target) &&
    browserFrameMatchesStatus(state.image.frame, status) &&
    state.dialog === null;
  const handlers = inputEnabled ? interaction : null;
  const image = state.type === "READY" ? state.image : null;
  const imageCurrent =
    image !== null &&
    status !== null &&
    browserFrameMatchesStatus(image.frame, status);
  const showDescription =
    state.type === "READY" &&
    (state.connection === "unavailable" ||
      (!state.canInput && !state.canClose));
  const description =
    state.type === "READY" && state.connection === "unavailable"
      ? t("transportUnavailable")
      : state.type === "READY" && !state.canInput && !state.canClose
        ? t("readOnlyDescription")
        : t("inputDescription");
  return (
    <Box className={classes.panel}>
      <Stack gap="sm" className={classes.header}>
        <Group gap="xs" justify="space-between" wrap="nowrap">
          <Text size="xs" c="dimmed" truncate className={classes.taskLabel}>
            {selected?.taskLabel || t("selectPage")}
          </Text>
          <Group gap="xs" wrap="nowrap">
            <Badge
              variant="filled"
              autoContrast
              color={connected ? "teal.9" : "gray.7"}
              role="status"
              size="sm"
            >
              {state.type === "READY"
                ? t(state.connection)
                : state.type === "CLOSED_TARGET"
                  ? t("closed")
                  : t("selectPage")}
            </Badge>
            {state.type === "READY" && !state.canInput && !state.canClose && (
              <Badge variant="filled" autoContrast color="gray.7" size="sm">
                {t("readOnly")}
              </Badge>
            )}
          </Group>
        </Group>
        <div
          className={classes.tabs}
          role="tablist"
          aria-label={t("page")}
          onKeyDown={(event) => {
            const tabs = Array.from(
              event.currentTarget.querySelectorAll<HTMLButtonElement>(
                '[role="tab"]',
              ),
            );
            const index = tabs.findIndex((tab) => tab === event.target);
            const next =
              event.key === "ArrowRight"
                ? (index + 1) % tabs.length
                : event.key === "ArrowLeft"
                  ? (index + tabs.length - 1) % tabs.length
                  : event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? tabs.length - 1
                      : null;
            if (index >= 0 && next !== null) {
              event.preventDefault();
              tabs[next]?.focus();
              tabs[next]?.click();
            }
          }}
        >
          {pages.map((page) => (
            <button
              key={JSON.stringify(page.target)}
              type="button"
              role="tab"
              aria-selected={
                selected !== null &&
                sameBrowserTarget(page.target, selected.target)
              }
              tabIndex={
                selected === null ||
                sameBrowserTarget(page.target, selected.target)
                  ? 0
                  : -1
              }
              className={classes.tab}
              title={`${page.taskLabel} · ${page.title || page.url || t("untitled")}`}
              onClick={() => onSelect(page.target)}
            >
              {page.title || page.url || t("untitled")}
            </button>
          ))}
        </div>
      </Stack>
      <div className={classes.browser}>
        <Group gap={rem(4)} wrap="nowrap" className={classes.addressBar}>
          <Tooltip label={t("back")}>
            <ActionIcon
              variant="subtle"
              color="gray"
              aria-label={t("back")}
              disabled={!(navigationEnabled && inputEnabled)}
              onClick={() =>
                onNavigate({ kind: "navigation", action: "back", url: null })
              }
            >
              <IconArrowLeft size={16} aria-hidden />
            </ActionIcon>
          </Tooltip>
          <Tooltip label={t("forward")}>
            <ActionIcon
              variant="subtle"
              color="gray"
              aria-label={t("forward")}
              disabled={!(navigationEnabled && inputEnabled)}
              onClick={() =>
                onNavigate({ kind: "navigation", action: "forward", url: null })
              }
            >
              <IconArrowRight size={16} aria-hidden />
            </ActionIcon>
          </Tooltip>
          <Tooltip label={t("reloadPage")}>
            <ActionIcon
              variant="subtle"
              color="gray"
              aria-label={t("reloadPage")}
              disabled={!(navigationEnabled && inputEnabled)}
              onClick={() =>
                onNavigate({ kind: "navigation", action: "reload", url: null })
              }
            >
              <IconReload size={16} aria-hidden />
            </ActionIcon>
          </Tooltip>
          <TextInput
            size="xs"
            variant="unstyled"
            className={classes.address}
            aria-label={t("address")}
            placeholder={t("addressPlaceholder")}
            leftSection={<IconWorld size={14} aria-hidden />}
            value={addressValue}
            readOnly={!(navigationEnabled && inputEnabled)}
            aria-invalid={addressError}
            onChange={(event) => onAddressChange(event.currentTarget.value)}
            onFocus={onAddressFocus}
            onBlur={onAddressBlur}
            onKeyDown={(event) => {
              if (event.key === "Enter" && navigationEnabled && inputEnabled) {
                event.preventDefault();
                onAddressSubmit();
              }
            }}
          />
          <Menu
            withinPortal
            position="bottom-end"
            returnFocus={false}
            trapFocus={false}
            withInitialFocusPlaceholder={false}
          >
            <Menu.Target>
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label={t("keyboardActions")}
              >
                <IconDots size={16} aria-hidden />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item
                onClick={onRetry}
                leftSection={<IconRefresh size={14} aria-hidden />}
              >
                {t("refreshConnection")}
              </Menu.Item>
              {handlers !== null && (
                <>
                  <Menu.Item
                    onClick={() => {
                      handlers.onSendTab(false);
                      keyboardRef?.current?.focus({ preventScroll: true });
                    }}
                  >
                    {t("sendTab")}
                  </Menu.Item>
                  <Menu.Item
                    onClick={() => {
                      handlers.onSendTab(true);
                      keyboardRef?.current?.focus({ preventScroll: true });
                    }}
                  >
                    {t("sendShiftTab")}
                  </Menu.Item>
                </>
              )}
            </Menu.Dropdown>
          </Menu>
          <Tooltip label={t("closePage")}>
            <ActionIcon
              variant="subtle"
              color="gray"
              aria-label={t("closePage")}
              disabled={state.type !== "READY" || !state.canClose}
              onClick={onClosePage}
            >
              <IconX size={16} aria-hidden />
            </ActionIcon>
          </Tooltip>
        </Group>
        <Stack gap="xs" className={classes.notices}>
          {addressError && (
            <Alert color="yellow" role="alert">
              {t("invalidAddress")}
            </Alert>
          )}
          {state.type === "CLOSED_TARGET" && (
            <Alert color="yellow">{t("closedTarget")}</Alert>
          )}
          {closeError && (
            <Alert color="yellow" role="alert">
              {t("closeFailed")}
            </Alert>
          )}
          {state.type === "READY" && state.conflict && (
            <Alert color="yellow" role="status">
              {t("conflict")}
            </Alert>
          )}
          {state.type === "READY" && state.outcomeUnknown && (
            <Alert color="yellow" role="status">
              {t("unknownOutcome")}
            </Alert>
          )}
          {state.type === "READY" && state.dialog !== null && (
            <Stack
              gap="xs"
              p="xs"
              className={classes.dialog}
              role="group"
              aria-label={t("dialog")}
            >
              <Text fw={600} size="sm">
                {t("dialog")}
              </Text>
              <Text size="sm" style={{ overflowWrap: "anywhere" }}>
                {state.dialog.message}
              </Text>
              {state.dialog.type === "prompt" && (
                <TextInput
                  maxLength={32768}
                  label={t("dialogText")}
                  value={dialogText}
                  onChange={(event) =>
                    onDialogTextChange(event.currentTarget.value)
                  }
                  disabled={!dialogEnabled}
                />
              )}
              <Group gap="xs">
                <Button
                  size="xs"
                  disabled={!dialogEnabled}
                  onClick={() => onDialogResponse(true)}
                >
                  {t("accept")}
                </Button>
                <Button
                  size="xs"
                  variant="default"
                  disabled={!dialogEnabled}
                  onClick={() => onDialogResponse(false)}
                >
                  {t("dismiss")}
                </Button>
              </Group>
            </Stack>
          )}
        </Stack>
        <div
          className={classes.viewport}
          data-stale={!connected || !imageCurrent}
          data-input={handlers !== null}
          role="region"
          aria-label={t("viewport")}
          aria-describedby={descriptionId}
          tabIndex={-1}
          onPointerDown={handlers?.onPointerDown}
          onPointerMove={handlers?.onPointerMove}
          onPointerUp={handlers?.onPointerUp}
          onPointerCancel={handlers?.onPointerCancel}
          onLostPointerCapture={handlers?.onLostPointerCapture}
          onWheel={handlers?.onWheel}
          onBlur={handlers?.onBlur}
          onContextMenu={handlers?.onContextMenu}
        >
          {image === null ? (
            <Text c="dimmed" p="md" role="status">
              {state.type === "CLOSED_TARGET"
                ? t("closedTarget")
                : state.type === "SELECT_PAGE"
                  ? t("selectPage")
                  : state.connection === "unavailable"
                    ? t("transportUnavailable")
                    : t("waitingFrame")}
            </Text>
          ) : (
            // eslint-disable-next-line @next/next/no-img-element -- Ephemeral live Blob frames bypass Next image optimization.
            <img
              key={image.url}
              className={classes.image}
              src={image.url}
              alt={t("frameAlt", { title: selected?.title || t("untitled") })}
              draggable={false}
              onLoad={(event) => {
                if (
                  event.currentTarget.naturalWidth !== image.frame.width ||
                  event.currentTarget.naturalHeight !== image.frame.height
                ) {
                  onFrameError(image);
                  return;
                }
                if (
                  status !== null &&
                  browserFrameMatchesStatus(image.frame, status)
                ) {
                  onFrameDisplayed(image);
                }
              }}
              onError={() => onFrameError(image)}
            />
          )}
          {image !== null && (!connected || !imageCurrent) && (
            <Text size="sm" className={classes.overlay} role="status">
              {connected ? t("oldImageDescription") : t("staleDescription")}
            </Text>
          )}
          {handlers !== null && (
            <textarea
              maxLength={32768}
              ref={keyboardRef}
              className={classes.keyboard}
              rows={1}
              tabIndex={0}
              aria-label={t("keyboard")}
              aria-describedby={descriptionId}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              onCompositionStart={handlers.onCompositionStart}
              onCompositionEnd={handlers.onCompositionEnd}
              onInput={handlers.onKeyboardInput}
              onKeyDown={handlers.onKeyDown}
              onKeyUp={handlers.onKeyUp}
            />
          )}
        </div>
      </div>
      {showDescription ? (
        <Text
          id={descriptionId}
          size="xs"
          c="dimmed"
          className={classes.footer}
        >
          {description}
        </Text>
      ) : (
        <VisuallyHidden id={descriptionId}>{description}</VisuallyHidden>
      )}
    </Box>
  );
}
