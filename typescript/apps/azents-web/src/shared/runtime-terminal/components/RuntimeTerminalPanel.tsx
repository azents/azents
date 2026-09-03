"use client";

import {
  ActionIcon,
  Alert,
  Box,
  Button,
  Group,
  Indicator,
  Paper,
  rem,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconArrowsMaximize,
  IconChevronUp,
  IconKeyboard,
  IconLayoutBottombar,
  IconPlayerPlay,
  IconRefresh,
  IconTerminal2,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { RuntimeTerminalContainerOutput } from "../containers/useRuntimeTerminalContainer";

interface RuntimeTerminalPanelProps {
  terminal: RuntimeTerminalContainerOutput;
  mobile: boolean;
  onStartRuntime: () => void;
}

const softwareKeys = [
  ["Esc", "\u001b"],
  ["Tab", "\t"],
  ["←", "\u001b[D"],
  ["↑", "\u001b[A"],
  ["↓", "\u001b[B"],
  ["→", "\u001b[C"],
] as const;

export function RuntimeTerminalPanel({
  terminal,
  mobile,
  onStartRuntime,
}: RuntimeTerminalPanelProps): React.ReactElement | null {
  const t = useTranslations("chat.terminal");
  const projection = terminal.projection;
  if (projection === null && !terminal.projectionLoading) {
    return null;
  }
  if (
    projection?.state === "absent" ||
    projection?.reason_code === "terminal_disabled" ||
    projection?.reason_code === "runtime_free_agent"
  ) {
    return null;
  }

  const focused = terminal.presentation === "focused";
  const collapsed = terminal.presentation === "collapsed";
  const canTerminate =
    projection?.state === "active" ||
    terminal.connection.type === "connecting" ||
    terminal.connection.type === "connected" ||
    terminal.connection.type === "reconnecting" ||
    terminal.connection.type === "terminating";
  const shellLabel =
    terminal.connection.type === "connected"
      ? terminal.connection.shellLabel
      : t(`connection.${terminal.connection.type}`);

  return (
    <Paper
      withBorder
      radius={0}
      style={{
        flexShrink: 0,
        ...(focused
          ? {
              position: mobile ? "fixed" : "relative",
              ...(mobile
                ? { height: "100dvh", inset: 0, zIndex: 300 }
                : { flex: 1, minHeight: 0 }),
            }
          : {}),
      }}
    >
      <Stack gap={0} style={focused ? { height: "100%" } : {}}>
        <Group
          justify="space-between"
          px="sm"
          py={6}
          wrap="nowrap"
          style={{ minHeight: rem(40) }}
        >
          <Group gap="xs" wrap="nowrap">
            <Indicator
              color={
                terminal.connection.type === "connected"
                  ? "green"
                  : terminal.connection.type === "error" ||
                      terminal.connection.type === "revoked"
                    ? "red"
                    : "yellow"
              }
              processing={
                terminal.connection.type === "connecting" ||
                terminal.connection.type === "reconnecting" ||
                terminal.connection.type === "terminating"
              }
              size={8}
            >
              <IconTerminal2 size={rem(18)} />
            </Indicator>
            <Text size="sm" fw={600} truncate>
              {shellLabel}
            </Text>
            {terminal.hasNewOutput ? (
              <Text size="xs" c="blue">
                {t("newOutput")}
              </Text>
            ) : null}
          </Group>
          <Group gap={4} wrap="nowrap">
            {collapsed ? (
              <Button
                size="compact-sm"
                variant="subtle"
                leftSection={<IconChevronUp size={rem(15)} />}
                onClick={terminal.onExpand}
              >
                {t("open")}
              </Button>
            ) : (
              <>
                {!mobile && !focused ? (
                  <Tooltip label={t("focus")}>
                    <ActionIcon
                      aria-label={t("focus")}
                      variant="subtle"
                      onClick={terminal.onFocus}
                    >
                      <IconArrowsMaximize size={rem(17)} />
                    </ActionIcon>
                  </Tooltip>
                ) : null}
                {focused && !mobile ? (
                  <Tooltip label={t("returnToDock")}>
                    <ActionIcon
                      aria-label={t("returnToDock")}
                      variant="subtle"
                      onClick={terminal.onReturnToDock}
                    >
                      <IconLayoutBottombar size={rem(17)} />
                    </ActionIcon>
                  </Tooltip>
                ) : null}
                {canTerminate ? (
                  <Button
                    color="red"
                    size="compact-xs"
                    variant="light"
                    onClick={terminal.onTerminate}
                  >
                    {t("terminate")}
                  </Button>
                ) : null}
                <Tooltip
                  label={focused && mobile ? t("backToChat") : t("collapse")}
                >
                  <ActionIcon
                    aria-label={
                      focused && mobile ? t("backToChat") : t("collapse")
                    }
                    variant="subtle"
                    onClick={terminal.onCollapse}
                  >
                    <IconX size={rem(17)} />
                  </ActionIcon>
                </Tooltip>
              </>
            )}
          </Group>
        </Group>

        {projection?.state === "stopped" && !collapsed ? (
          <Alert
            m="sm"
            icon={<IconPlayerPlay size={rem(18)} />}
            title={t("stoppedTitle")}
          >
            <Stack gap="sm">
              <Text size="sm">{t("stoppedDescription")}</Text>
              {projection.can_start_runtime ? (
                <Button size="xs" onClick={onStartRuntime}>
                  {t("startRuntime")}
                </Button>
              ) : null}
            </Stack>
          </Alert>
        ) : null}
        {projection?.state === "starting" && !collapsed ? (
          <Alert m="sm" title={t("startingTitle")}>
            {t("startingDescription")}
          </Alert>
        ) : null}
        {projection?.state === "unavailable" && !collapsed ? (
          <Alert color="yellow" m="sm" title={t("unavailableTitle")}>
            {t("unavailableDescription")}
          </Alert>
        ) : null}
        {terminal.replayTruncated && !collapsed ? (
          <Alert color="yellow" mx="sm" mb="xs">
            {t("replayTruncated")}
          </Alert>
        ) : null}
        {(terminal.connection.type === "error" ||
          terminal.connection.type === "revoked" ||
          terminal.connection.type === "exited") &&
        !collapsed ? (
          <Alert color="yellow" mx="sm" mb="xs">
            <Group justify="space-between">
              <Text size="sm">
                {t(`stateMessage.${terminal.connection.type}`)}
              </Text>
              <Button
                size="compact-xs"
                variant="subtle"
                leftSection={<IconRefresh size={rem(14)} />}
                onClick={terminal.onRetry}
              >
                {t("retry")}
              </Button>
            </Group>
          </Alert>
        ) : null}

        {!mobile && terminal.presentation === "docked" ? (
          <Box
            aria-label={t("resizeDock")}
            aria-orientation="horizontal"
            role="separator"
            tabIndex={0}
            h={rem(6)}
            style={{
              cursor: "row-resize",
              borderTop: `${rem(1)} solid var(--mantine-color-default-border)`,
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowUp") {
                event.preventDefault();
                terminal.onDockResizeBy(24);
              } else if (event.key === "ArrowDown") {
                event.preventDefault();
                terminal.onDockResizeBy(-24);
              }
            }}
            onPointerDown={(event) => terminal.onDockResizeStart(event.clientY)}
          />
        ) : null}
        <Box
          style={{
            display: collapsed ? "none" : "block",
            ...(focused ? { flex: 1 } : { height: rem(terminal.dockHeight) }),
            minHeight: 0,
            background: "var(--mantine-color-dark-9)",
          }}
        >
          <Box ref={terminal.hostRef} h="100%" p={6} />
        </Box>

        {mobile && focused ? (
          <ScrollArea type="never" offsetScrollbars={false}>
            <Group
              gap={4}
              px="xs"
              pt="xs"
              wrap="nowrap"
              style={{
                paddingBottom:
                  "calc(var(--mantine-spacing-xs) + env(safe-area-inset-bottom))",
              }}
            >
              <Button
                size="compact-xs"
                variant={terminal.ctrlActive ? "filled" : "default"}
                onClick={terminal.onToggleCtrl}
              >
                Ctrl
              </Button>
              <Button
                size="compact-xs"
                variant={terminal.altActive ? "filled" : "default"}
                onClick={terminal.onToggleAlt}
              >
                Alt
              </Button>
              {softwareKeys.map(([label, key]) => (
                <Button
                  key={label}
                  size="compact-xs"
                  variant="default"
                  onClick={() => terminal.onSoftwareKey(key)}
                >
                  {label}
                </Button>
              ))}
              <ActionIcon
                aria-label={t("focusKeyboard")}
                variant="default"
                onClick={terminal.onFocusKeyboard}
              >
                <IconKeyboard size={rem(16)} />
              </ActionIcon>
            </Group>
          </ScrollArea>
        ) : null}
      </Stack>
    </Paper>
  );
}
