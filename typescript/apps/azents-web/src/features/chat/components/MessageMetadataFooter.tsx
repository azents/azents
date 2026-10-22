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
import { useLocale, useTranslations } from "next-intl";
import { useMemo } from "react";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import {
  MessageMetadataVisibilityContext,
  useMessageMetadataSurfaceController,
  useMessageTimestampController,
  useModelMetadataController,
} from "../containers/useMessageMetadataController";
import classes from "./MessageMetadataFooter.module.css";
import type {
  MessageMetadataSurfaceOutput,
  MessageTimestampOutput,
  ModelMetadataOutput,
} from "../containers/useMessageMetadataController";
import type {
  AppliedInferenceProfile,
  RequestedInferenceProfile,
} from "@azents/public-client";

type ChatTranslator = ReturnType<typeof useTranslations<"chat">>;

type MessageInferenceProfile =
  RequestedInferenceProfile | AppliedInferenceProfile;

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

const MessageTimestamp = createReactContainer(
  "MessageTimestamp",
  useMessageTimestampController,
  MessageTimestampView,
);

export function MessageTimestampView({
  createdAt,
  isTouchPrimary,
  opened,
  handlePointerDown,
}: MessageTimestampOutput): React.ReactElement {
  const locale = useLocale();
  const t = useTranslations("chat");
  const relativeTime = formatRelativeTime(createdAt, t);
  const fullDateTime = useMemo(
    () => formatFullDateTime(createdAt, locale),
    [createdAt, locale],
  );

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
        opened={opened}
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

function useModelMetadataWithProfile(props: {
  profile: MessageInferenceProfile;
}): ModelMetadataOutput & { profile: MessageInferenceProfile } {
  return { ...props, ...useModelMetadataController() };
}
const ModelMetadata = createReactContainer(
  "ModelMetadata",
  useModelMetadataWithProfile,
  ModelMetadataView,
);

export function ModelMetadataView({
  profile,
  opened,
  setOpened,
}: ModelMetadataOutput & {
  profile: MessageInferenceProfile;
}): React.ReactElement {
  const t = useTranslations("chat.inferenceProvenance");
  const actualModel = profileModelDisplayName(profile);
  const effort = profile.reasoning_effort ?? t("defaultEffort");

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
        bg="var(--azents-color-inverse)"
        c="var(--azents-color-on-inverse)"
        style={{
          border: 0,
          maxWidth: `min(80vw, ${rem(360)})`,
        }}
        data-message-metadata-popover
      >
        <Group gap={rem(4)} wrap="nowrap">
          <Text size="sm" truncate>
            {profile.model_target_label}
          </Text>
          {actualModel !== null && (
            <>
              <Text
                component="span"
                size="sm"
                c="var(--azents-color-inverse-muted)"
                aria-hidden="true"
              >
                ·
              </Text>
              <Text size="sm" truncate>
                {actualModel}
              </Text>
            </>
          )}
          <Text
            component="span"
            size="sm"
            c="var(--azents-color-inverse-muted)"
            aria-hidden="true"
          >
            ·
          </Text>
          <Text size="sm">{effort}</Text>
        </Group>
      </Popover.Dropdown>
    </Popover>
  );
}

export const MessageMetadataSurface = createReactContainer(
  "MessageMetadataSurface",
  useMessageMetadataSurfaceController,
  MessageMetadataSurfaceView,
);

export function MessageMetadataSurfaceView({
  children,
  value,
  visible,
  showForTouch,
}: MessageMetadataSurfaceOutput): React.ReactElement {
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
