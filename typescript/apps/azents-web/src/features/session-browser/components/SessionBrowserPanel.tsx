"use client";

import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  FocusTrap,
  Group,
  Loader,
  Menu,
  OptionalPortal,
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
  IconMaximize,
  IconMinimize,
  IconPlus,
  IconRefresh,
  IconReload,
  IconWorld,
  IconX,
  IconZoomIn,
  IconZoomOut,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { browserFrameMatchesStatus, sameBrowserTarget } from "../input";
import classes from "./SessionBrowserPanel.module.css";
import type { BrowserTouchView } from "../containers/useBrowserTouchView";
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
  ReactNode,
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
  focused: boolean;
  focusViewport: { top: number; height: number } | null;
  zoom: number;
  onToggleFocus: () => void;
  onZoomChange: (zoom: number) => void;
  state: BrowserViewState;
  closeError: boolean;
  createError: boolean;
  creating: boolean;
  canCreate: boolean;
  onCreatePage: () => void;
  onSelect: (target: BrowserTarget) => void;
  onClosePage: (target: BrowserTarget) => void;
  onRetry: () => void;
  onFrameDisplayed: (image: BrowserImage) => void;
  onFrameError: (image: BrowserImage) => void;
  onDialogResponse: (accept: boolean) => void;
  dialogText: string;
  onDialogTextChange: (text: string) => void;
  keyboardRef: RefObject<HTMLTextAreaElement | null> | null;
  interaction: BrowserInteractionHandlers | null;
  touchView: BrowserTouchView | null;
  addressValue: string;
  addressError: boolean;
  navigationEnabled: boolean;
  onAddressChange: (value: string) => void;
  onAddressFocus: () => void;
  onAddressBlur: () => void;
  onAddressSubmit: () => void;
  onNavigate: (action: BrowserNavigationAction) => void;
}

function BrowserShell({
  focused,
  focusViewport,
  label,
  children,
}: {
  focused: boolean;
  focusViewport: SessionBrowserPanelProps["focusViewport"];
  label: string;
  children: ReactNode;
}): ReactElement {
  return (
    <OptionalPortal withinPortal={focused}>
      <FocusTrap active={focused}>
        <Box
          className={classes.panel}
          data-focused={focused}
          style={
            focused && focusViewport !== null
              ? {
                  top: rem(focusViewport.top),
                  height: rem(focusViewport.height),
                }
              : {}
          }
          {...(focused
            ? { role: "dialog", "aria-modal": true, "aria-label": label }
            : {})}
        >
          {children}
        </Box>
      </FocusTrap>
    </OptionalPortal>
  );
}

export function SessionBrowserPanel({
  focused,
  focusViewport,
  zoom,
  onToggleFocus,
  onZoomChange,
  state,
  closeError,
  createError,
  creating,
  canCreate,
  onCreatePage,
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
  touchView,
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
      <BrowserShell
        focused={focused}
        focusViewport={focusViewport}
        label={t("focusBrowser")}
      >
        {focused && (
          <Group p="xs" justify="flex-end">
            <Button
              variant="subtle"
              leftSection={<IconMinimize size={16} />}
              onClick={onToggleFocus}
            >
              {t("exitFocus")}
            </Button>
          </Group>
        )}
        <Stack p="md" align="center" justify="center" flex={1}>
          <Text fw={600}>{t("emptyTitle")}</Text>
          <Text size="sm">
            {canCreate ? t("emptyDescription") : t("readOnlyDescription")}
          </Text>
          {createError && (
            <Alert color="yellow" role="alert">
              {t("createFailed")}
            </Alert>
          )}
          <Button
            disabled={!canCreate}
            loading={creating}
            onClick={onCreatePage}
            leftSection={<IconPlus size={16} />}
          >
            {t("newTab")}
          </Button>
          <Button variant="subtle" onClick={onRetry}>
            {t("refresh")}
          </Button>
        </Stack>
      </BrowserShell>
    );
  }
  const pages = state.pages;
  const selected = state.selected;
  const connected = state.connection === "connected";
  const status = state.status;
  const dialogEnabled =
    connected &&
    state.canInput &&
    status?.state === "connected" &&
    status.allow_input &&
    sameBrowserTarget(status.target, state.selected.target) &&
    status.dialog !== null &&
    status.dialog.id === state.dialog?.id;
  const inputEnabled =
    connected &&
    state.canInput &&
    state.image !== null &&
    status !== null &&
    status.allow_input &&
    sameBrowserTarget(status.target, state.selected.target) &&
    browserFrameMatchesStatus(state.image.frame, status) &&
    state.dialog === null;
  const handlers = inputEnabled && focused ? interaction : null;
  const touch = focused ? touchView?.touch : null;
  const image = state.image;
  const imageCurrent =
    image !== null &&
    status !== null &&
    browserFrameMatchesStatus(image.frame, status);
  const showDescription =
    state.connection === "unavailable" || (!state.canInput && !state.canClose);
  const description =
    state.connection === "unavailable"
      ? t("transportUnavailable")
      : !state.canInput && !state.canClose
        ? t("readOnlyDescription")
        : t("inputDescription");
  return (
    <BrowserShell
      focused={focused}
      focusViewport={focusViewport}
      label={t("focusBrowser")}
    >
      <Stack gap="sm" className={classes.header}>
        <Group gap="xs" justify="space-between" wrap="nowrap">
          <Text size="xs" c="dimmed" truncate className={classes.taskLabel}>
            {selected.taskLabel || t("title")}
          </Text>
          <Group gap="xs" wrap="nowrap">
            {focused ? (
              <Button
                size="xs"
                variant="subtle"
                leftSection={<IconMinimize size={16} aria-hidden />}
                onClick={onToggleFocus}
              >
                {t("exitFocus")}
              </Button>
            ) : (
              <Tooltip label={t("focusBrowser")}>
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  aria-label={t("focusBrowser")}
                  onClick={onToggleFocus}
                >
                  <IconMaximize size={16} aria-hidden />
                </ActionIcon>
              </Tooltip>
            )}
            <Badge
              variant="filled"
              autoContrast
              color={connected ? "teal.9" : "gray.7"}
              role="status"
              size="sm"
            >
              {t(state.connection)}
            </Badge>
            {!state.canInput && !state.canClose && (
              <Badge variant="filled" autoContrast color="gray.7" size="sm">
                {t("readOnly")}
              </Badge>
            )}
          </Group>
        </Group>
        <div className={classes.tabsChrome}>
          <div className={classes.tabScroll}>
            <div className={classes.tabsContent}>
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
                    aria-selected={sameBrowserTarget(
                      page.target,
                      selected.target,
                    )}
                    tabIndex={
                      sameBrowserTarget(page.target, selected.target) ? 0 : -1
                    }
                    className={classes.tab}
                    title={`${page.taskLabel} · ${page.title || page.url || t("untitled")}`}
                    onClick={() => onSelect(page.target)}
                  >
                    {page.title || page.url || t("untitled")}
                  </button>
                ))}
              </div>
              <div className={classes.tabCloseControls}>
                {pages.map((page) => (
                  <div
                    className={classes.tabCloseSlot}
                    key={JSON.stringify(page.target)}
                  >
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      size="sm"
                      className={classes.closeTab}
                      aria-label={t("closeTab", {
                        title: page.title || page.url || t("untitled"),
                      })}
                      disabled={!state.canClose}
                      onClick={() => onClosePage(page.target)}
                    >
                      <IconX size={14} aria-hidden />
                    </ActionIcon>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <Tooltip label={t("newTab")}>
            <ActionIcon
              variant="subtle"
              color="gray"
              className={classes.newTab}
              aria-label={t("newTab")}
              disabled={!canCreate}
              loading={creating}
              onClick={onCreatePage}
            >
              <IconPlus size={18} aria-hidden />
            </ActionIcon>
          </Tooltip>
        </div>
      </Stack>
      <div className={classes.browser}>
        <Group gap={rem(4)} wrap="nowrap" className={classes.addressBar}>
          <Group
            gap={rem(4)}
            wrap="nowrap"
            className={classes.navigationControls}
          >
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
                  onNavigate({
                    kind: "navigation",
                    action: "forward",
                    url: null,
                  })
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
                  onNavigate({
                    kind: "navigation",
                    action: "reload",
                    url: null,
                  })
                }
              >
                <IconReload size={16} aria-hidden />
              </ActionIcon>
            </Tooltip>
          </Group>
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
                event.currentTarget.blur();
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
                disabled={zoom <= 1}
                onClick={() => onZoomChange(Math.max(1, zoom - 0.25))}
                leftSection={<IconZoomOut size={14} aria-hidden />}
              >
                {t("zoomOut")}
              </Menu.Item>
              <Menu.Item
                disabled={zoom >= 3}
                onClick={() => onZoomChange(Math.min(3, zoom + 0.25))}
                leftSection={<IconZoomIn size={14} aria-hidden />}
              >
                {t("zoomIn")}
              </Menu.Item>
              <Menu.Item onClick={() => onZoomChange(1)}>
                {t("resetZoom", { percent: Math.round(zoom * 100) })}
              </Menu.Item>
              <Menu.Divider />
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
        </Group>
        <Stack gap="xs" className={classes.notices}>
          {addressError && (
            <Alert color="yellow" role="alert">
              {t("invalidAddress")}
            </Alert>
          )}
          {closeError && (
            <Alert color="yellow" role="alert">
              {t("closeFailed")}
            </Alert>
          )}
          {createError && (
            <Alert color="yellow" role="alert">
              {t("createFailed")}
            </Alert>
          )}
          {state.conflict && (
            <Alert color="yellow" role="status">
              {t("conflict")}
            </Alert>
          )}
          {state.outcomeUnknown && (
            <Alert color="yellow" role="status">
              {t("unknownOutcome")}
            </Alert>
          )}
          {state.dialog !== null && (
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
          className={classes.viewWindow}
          ref={touchView?.viewWindowRef}
          tabIndex={focused && handlers === null ? 0 : -1}
        >
          <div
            className={classes.viewport}
            style={{
              width: `${(focused ? zoom : 1) * 100}%`,
              ...(image === null
                ? {}
                : {
                    aspectRatio: `${image.frame.width} / ${image.frame.height}`,
                  }),
            }}
            data-stale={!connected || !imageCurrent}
            data-input={handlers !== null}
            data-focused={focused}
            role="region"
            aria-label={t("viewport")}
            aria-describedby={descriptionId}
            tabIndex={-1}
            onPointerDown={(event) =>
              event.pointerType === "touch"
                ? touch?.onPointerDown(event)
                : handlers?.onPointerDown(event)
            }
            onPointerMove={(event) =>
              event.pointerType === "touch"
                ? touch?.onPointerMove(event)
                : handlers?.onPointerMove(event)
            }
            onPointerUp={(event) =>
              event.pointerType === "touch"
                ? touch?.onPointerUp(event)
                : handlers?.onPointerUp(event)
            }
            onPointerCancel={(event) =>
              event.pointerType === "touch"
                ? touch?.onPointerCancel(event)
                : handlers?.onPointerCancel(event)
            }
            onLostPointerCapture={(event) =>
              event.pointerType === "touch"
                ? touch?.onLostPointerCapture(event)
                : handlers?.onLostPointerCapture(event)
            }
            onWheel={handlers?.onWheel}
            onBlur={handlers?.onBlur}
            onContextMenu={handlers?.onContextMenu}
          >
            {image === null ? (
              <Text c="dimmed" p="md" role="status">
                {state.connection === "unavailable"
                  ? t("transportUnavailable")
                  : t("waitingFrame")}
              </Text>
            ) : (
              // eslint-disable-next-line @next/next/no-img-element -- Ephemeral live Blob frames bypass Next image optimization.
              <img
                className={classes.image}
                src={image.url}
                alt={t("frameAlt", {
                  title: selected.title || t("untitled"),
                })}
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
            {!focused && (
              <button
                type="button"
                className={classes.preview}
                aria-label={t("focusBrowser")}
                onClick={onToggleFocus}
              />
            )}
            {focused &&
              touchView != null &&
              touchView.touchFeedback !== null && (
                <span
                  key={touchView.touchFeedback.id}
                  className={classes.touchFeedback}
                  aria-hidden
                  data-browser-touch-feedback
                  style={{
                    left: `${touchView.touchFeedback.x}%`,
                    top: `${touchView.touchFeedback.y}%`,
                  }}
                  onAnimationEnd={touchView.onTouchFeedbackEnd}
                />
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
    </BrowserShell>
  );
}
