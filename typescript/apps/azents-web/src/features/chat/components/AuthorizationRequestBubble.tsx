"use client";
import { Alert, Button, Group, Text } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";

/**
 * OAuth2 per-user authorization request card.
 *
 * toolkit user auth required with to when chat to is shown..
 * authorization URL new tab in can open button includes..
 */

import { useAuthorizationRequestBubbleController } from "../containers/useAuthorizationRequestBubbleController";
import { ChatTimelineItem } from "./ChatTimelineItem";
import type { AuthorizationRequestBubbleViewProps } from "../containers/useAuthorizationRequestBubbleController";

interface AuthorizationRequestBubbleProps {
  toolkitName: string;
  authorizationUrl: string;
  variant?: "card" | "compact";
  /** authorizationUrl event to absent when click time to authorization URL fetches.. */
  getAuthorizationUrl?: () => Promise<string | null>;
  /** auth complete when callback called */
  onAuthorized: () => void;
}

export function AuthorizationRequestBubble(
  props: AuthorizationRequestBubbleProps,
): React.ReactElement {
  return (
    <AuthorizationRequestBubbleView
      {...useAuthorizationRequestBubbleController(props)}
    />
  );
}

export function AuthorizationRequestBubbleView({
  toolkitName,
  variant,
  t,
  isOpening,
  handleClick,
}: AuthorizationRequestBubbleViewProps): React.ReactElement {
  if (variant === "compact") {
    return (
      <Button
        size="compact-xs"
        variant="default"
        leftSection={<IconLock size={14} />}
        onClick={() => void handleClick()}
        loading={isOpening}
        aria-label={t("authorizationRequestMessage", { toolkitName })}
      >
        {t("reviewButton")}
      </Button>
    );
  }

  return (
    <ChatTimelineItem>
      <Group align="flex-start" gap="sm" justify="flex-start" wrap="nowrap">
        <Alert
          icon={<IconLock size={18} />}
          title={t("authorizationRequired")}
          color="yellow"
          variant="light"
          maw="100%"
        >
          <Text size="sm" mb="sm">
            {t("authorizationRequestMessage", { toolkitName })}
          </Text>
          <Button
            size="sm"
            variant="filled"
            onClick={() => void handleClick()}
            loading={isOpening}
          >
            {t("authorizeButton")}
          </Button>
        </Alert>
      </Group>
    </ChatTimelineItem>
  );
}
