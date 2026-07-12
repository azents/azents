"use client";

import {
  Box,
  Group,
  Popover,
  rem,
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
  AppliedInferenceProfile,
  RequestedInferenceProfile,
} from "@azents/public-client";

type ChatTranslator = ReturnType<typeof useTranslations<"chat">>;

interface MessageMetadataVisibilityContextValue {
  activeOverlay: "model" | "timestamp" | null;
  isTouchPrimary: boolean;
  visible: boolean;
  setActiveOverlay: (overlay: "model" | "timestamp" | null) => void;
  showForTouch: () => void;
}

type MessageInferenceProfile =
  | RequestedInferenceProfile
  | AppliedInferenceProfile;

function profileModelDisplayName(
  profile: MessageInferenceProfile,
): string | null {
  if (!("model_display_name" in profile)) {
    return null;
  }
  const value = profile.model_display_name;
  return typeof value === "string" ? value : null;
}

interface MessageMetadataFooterProps {
  createdAt: string;
  profile?: MessageInferenceProfile | null;
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
  const [relativeTimeTick, setRelativeTimeTick] = useState(0);
  const relativeTime = formatRelativeTime(createdAt, t);
  const fullDateTime = useMemo(
    () => formatFullDateTime(createdAt, locale),
    [createdAt, locale],
  );

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
    visibility.setActiveOverlay(
      visibility.activeOverlay === "timestamp" ? null : "timestamp",
    );
  }

  const timestamp = (
    <Text
      component="time"
      dateTime={createdAt}
      size="xs"
      c="dimmed"
      aria-label={fullDateTime}
      data-message-metadata="timestamp"
      data-message-metadata-trigger="timestamp"
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
        opened={visibility?.activeOverlay === "timestamp" && visibility.visible}
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

function ModelMetadata({
  profile,
}: {
  profile: MessageInferenceProfile;
}): React.ReactElement {
  const t = useTranslations("chat.inferenceProvenance");
  const visibility = useContext(MessageMetadataVisibilityContext);
  const [desktopOpened, setDesktopOpened] = useState(false);
  const isTouchPrimary = visibility?.isTouchPrimary ?? false;
  const opened = isTouchPrimary
    ? visibility?.activeOverlay === "model"
    : desktopOpened;
  const actualModel = profileModelDisplayName(profile);
  const effort = profile.reasoning_effort ?? t("defaultEffort");

  function setOpened(nextOpened: boolean): void {
    if (isTouchPrimary && visibility !== null) {
      visibility.setActiveOverlay(nextOpened ? "model" : null);
      return;
    }
    setDesktopOpened(nextOpened);
  }

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position="bottom-end"
      width="auto"
      shadow="none"
      withArrow
      withinPortal
    >
      <Popover.Target>
        <UnstyledButton
          aria-label={t("detailsAriaLabel", {
            target: profile.model_target_label,
          })}
          data-message-metadata-trigger="model"
          onClick={() => setOpened(!opened)}
        >
          <Text
            component="span"
            size="xs"
            c="dimmed"
            data-message-metadata="model"
            style={{ display: "block" }}
          >
            {profile.model_target_label}
          </Text>
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown
        px="xs"
        py={rem(5)}
        bg="gray.9"
        c="white"
        style={{
          border: 0,
          maxWidth: `min(80vw, ${rem(360)})`,
        }}
        data-message-metadata-popover
      >
        <Group gap={rem(4)} wrap="nowrap">
          <Text size="sm" c="white" truncate>
            {profile.model_target_label}
          </Text>
          {actualModel !== null && (
            <>
              <Text component="span" size="sm" c="gray.5" aria-hidden="true">
                ·
              </Text>
              <Text size="sm" c="white" truncate>
                {actualModel}
              </Text>
            </>
          )}
          <Text component="span" size="sm" c="gray.5" aria-hidden="true">
            ·
          </Text>
          <Text size="sm" c="white">
            {effort}
          </Text>
        </Group>
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
  const [activeOverlay, setActiveOverlay] = useState<
    "model" | "timestamp" | null
  >(null);
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

  useEffect(() => {
    if (!isTouchPrimary || activeOverlay === null) {
      return;
    }

    function dismissOverlay(event: PointerEvent): void {
      if (
        event.target instanceof Element &&
        event.target.closest(
          `[data-message-metadata-trigger="${activeOverlay}"], [data-message-metadata-popover]`,
        )
      ) {
        return;
      }
      setActiveOverlay(null);
    }

    document.addEventListener("pointerdown", dismissOverlay, true);
    return () =>
      document.removeEventListener("pointerdown", dismissOverlay, true);
  }, [activeOverlay, isTouchPrimary]);

  const showForTouch = useCallback((): void => {
    if (!isTouchPrimary) {
      return;
    }
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
    }
    setVisible(true);
    hideTimerRef.current = setTimeout(() => {
      setActiveOverlay(null);
      setVisible(false);
      hideTimerRef.current = null;
    }, 5000);
  }, [isTouchPrimary]);

  const value = useMemo(
    () => ({
      activeOverlay,
      isTouchPrimary,
      visible,
      setActiveOverlay,
      showForTouch,
    }),
    [activeOverlay, isTouchPrimary, showForTouch, visible],
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
}: MessageMetadataFooterProps): React.ReactElement {
  return (
    <Group
      gap={rem(4)}
      wrap="nowrap"
      align="baseline"
      className={classes.metadata}
    >
      <MessageTimestamp createdAt={createdAt} />
      {profile !== null && (
        <>
          <Text
            component="span"
            size="xs"
            c="dimmed"
            aria-hidden="true"
            data-message-metadata="separator"
          >
            ·
          </Text>
          <ModelMetadata profile={profile} />
        </>
      )}
    </Group>
  );
}
