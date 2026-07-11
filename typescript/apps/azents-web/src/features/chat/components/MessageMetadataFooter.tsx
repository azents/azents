"use client";

import {
  Box,
  Group,
  Paper,
  Popover,
  rem,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { useLocale, useTranslations } from "next-intl";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import classes from "./MessageMetadataFooter.module.css";
import type {
  InferenceRunSummary,
  RequestedInferenceProfile,
} from "@azents/public-client";

type ChatTranslator = ReturnType<typeof useTranslations<"chat">>;

interface MessageMetadataVisibilityContextValue {
  isTouchPrimary: boolean;
  visible: boolean;
  showForTouch: () => void;
}

interface MessageMetadataFooterProps {
  createdAt: string;
  profile?: RequestedInferenceProfile | null;
  summary?: InferenceRunSummary | null;
}

const MessageMetadataVisibilityContext =
  createContext<MessageMetadataVisibilityContextValue | null>(null);
const FADE_DURATION_MS = 160;

function formatRelativeTime(iso: string, t: ChatTranslator): string {
  const createdAt = new Date(iso).getTime();
  if (!Number.isFinite(createdAt)) {
    return "";
  }

  const diff = Math.max(0, Date.now() - createdAt);
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) {
    return t("justNow");
  }
  if (minutes < 60) {
    return t("minutesAgo", { count: minutes });
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return t("hoursAgo", { count: hours });
  }

  return t("daysAgo", { count: Math.floor(hours / 24) });
}

function formatFullDateTime(iso: string, locale: string): string {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) {
    return iso;
  }

  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(date);
}

function getNextRelativeTimeDelay(iso: string): number {
  const createdAt = new Date(iso).getTime();
  if (!Number.isFinite(createdAt)) {
    return 60_000;
  }

  const diff = Math.max(0, Date.now() - createdAt);
  return diff < 60_000 ? 60_000 - diff : 60_000 - (diff % 60_000);
}

function MessageTimestamp({
  createdAt,
}: {
  createdAt: string;
}): React.ReactElement {
  const locale = useLocale();
  const t = useTranslations("chat");
  const visibility = useContext(MessageMetadataVisibilityContext);
  const isTouchPrimary = visibility?.isTouchPrimary ?? false;
  const [tooltipOpened, setTooltipOpened] = useState(false);
  const [relativeTimeTick, setRelativeTimeTick] = useState(0);
  const relativeTime = formatRelativeTime(createdAt, t);
  const fullDateTime = useMemo(
    () => formatFullDateTime(createdAt, locale),
    [createdAt, locale],
  );

  useEffect(() => {
    if (!visibility?.visible) {
      setTooltipOpened(false);
    }
  }, [visibility?.visible]);

  useEffect(() => {
    const delay = getNextRelativeTimeDelay(createdAt);
    const timer = setTimeout(
      () => setRelativeTimeTick((current) => current + 1),
      delay,
    );
    return () => clearTimeout(timer);
  }, [createdAt, relativeTimeTick]);

  function handlePointerDown(event: React.PointerEvent<HTMLElement>): void {
    if (!isTouchPrimary || visibility === null) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    visibility.showForTouch();
    setTooltipOpened((opened) => !opened);
  }

  const timestamp = (
    <Text
      component="time"
      dateTime={createdAt}
      size="xs"
      c="dimmed"
      aria-label={fullDateTime}
      tabIndex={0}
      onPointerDown={handlePointerDown}
    >
      {relativeTime}
    </Text>
  );

  if (isTouchPrimary) {
    return (
      <Tooltip
        label={fullDateTime}
        withArrow
        opened={tooltipOpened && visibility?.visible}
        transitionProps={{ transition: "fade", duration: FADE_DURATION_MS }}
      >
        {timestamp}
      </Tooltip>
    );
  }

  return (
    <Tooltip
      label={fullDateTime}
      withArrow
      transitionProps={{ transition: "fade", duration: FADE_DURATION_MS }}
    >
      {timestamp}
    </Tooltip>
  );
}

function MetadataRow({
  label,
  value,
}: {
  label: string;
  value: string;
}): React.ReactElement {
  return (
    <Group justify="space-between" gap="lg" wrap="nowrap" align="flex-start">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="xs" fw={500} ta="right" style={{ overflowWrap: "anywhere" }}>
        {value}
      </Text>
    </Group>
  );
}

function ModelMetadata({
  profile,
  summary,
}: {
  profile: RequestedInferenceProfile;
  summary: InferenceRunSummary | null;
}): React.ReactElement {
  const t = useTranslations("chat.inferenceProvenance");
  const [opened, setOpened] = useState(false);
  const requestedProfile = summary?.requested_profile ?? profile;
  const actualModel = summary?.resolved_profile?.model_display_name ?? "—";
  const effort = requestedProfile.reasoning_effort ?? t("defaultEffort");

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-end"
      width="auto"
      shadow="none"
      withinPortal
    >
      <Popover.Target>
        <UnstyledButton
          className={classes.modelTrigger}
          aria-label={t("detailsAriaLabel", {
            target: requestedProfile.model_target_label,
          })}
          onClick={() => setOpened((current) => !current)}
        >
          <Text component="span" size="xs" c="dimmed">
            {requestedProfile.model_target_label}
          </Text>
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown
        p={0}
        style={{
          background: "transparent",
          border: 0,
          boxShadow: "none",
          overflow: "visible",
        }}
      >
        <Paper
          withBorder
          radius={rem(12)}
          shadow="md"
          p={rem(10)}
          className={classes.popoverDropdown}
        >
          <Stack gap="xs">
            <MetadataRow
              label={t("modelLabel")}
              value={requestedProfile.model_target_label}
            />
            <MetadataRow label={t("actualModel")} value={actualModel} />
            <MetadataRow label={t("reasoningEffort")} value={effort} />
          </Stack>
        </Paper>
      </Popover.Dropdown>
    </Popover>
  );
}

export function MessageMetadataSurface({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  const isTouchPrimary = useMediaQuery("(hover: none)");
  const [visible, setVisible] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (hideTimerRef.current) {
        clearTimeout(hideTimerRef.current);
      }
    },
    [],
  );

  const showForTouch = useCallback((): void => {
    if (!isTouchPrimary) {
      return;
    }
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
    }
    setVisible(true);
    hideTimerRef.current = setTimeout(() => {
      setVisible(false);
      hideTimerRef.current = null;
    }, 5000);
  }, [isTouchPrimary]);

  const value = useMemo(
    () => ({ isTouchPrimary, visible, showForTouch }),
    [isTouchPrimary, showForTouch, visible],
  );

  return (
    <MessageMetadataVisibilityContext.Provider value={value}>
      <Box
        className={classes.messageSurface}
        data-metadata-visible={visible}
        onPointerDown={showForTouch}
      >
        {children}
      </Box>
    </MessageMetadataVisibilityContext.Provider>
  );
}

export function MessageMetadataFooter({
  createdAt,
  profile = null,
  summary = null,
}: MessageMetadataFooterProps): React.ReactElement {
  return (
    <Group gap={rem(4)} wrap="nowrap" className={classes.metadata}>
      <MessageTimestamp createdAt={createdAt} />
      {profile !== null && (
        <>
          <Text component="span" size="xs" c="dimmed" aria-hidden="true">
            ·
          </Text>
          <ModelMetadata profile={profile} summary={summary} />
        </>
      )}
    </Group>
  );
}
