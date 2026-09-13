"use client";

import {
  Alert,
  Anchor,
  Button,
  Container,
  Group,
  Paper,
  rem,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import {
  IconBrandDiscord,
  IconBrandSlack,
  IconCheck,
  IconExternalLink,
  IconLock,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type {
  ExternalAccountOAuthResultState,
  ExternalAccountProvider,
} from "../types";

export interface ExternalAccountOAuthResultProps {
  state: ExternalAccountOAuthResultState;
}

function providerIcon(provider: ExternalAccountProvider): React.ReactElement {
  return provider === "discord" ? (
    <IconBrandDiscord size={24} />
  ) : (
    <IconBrandSlack size={24} />
  );
}

export function ExternalAccountOAuthResult({
  state,
}: ExternalAccountOAuthResultProps): React.ReactElement {
  const t = useTranslations("externalAccountLinks");
  const provider = state.type === "AUTH_REQUIRED" ? null : state.provider;
  const providerLabel =
    provider === null
      ? t("oauthResult.externalAccount")
      : t(`providers.${provider}`);

  let color: "blue" | "green" | "gray" | "red" = "red";
  let icon: React.ReactElement = <IconX size={24} />;
  let title = t("oauthResult.failedTitle");
  let description = t("oauthResult.failure.invalid_callback");

  switch (state.type) {
    case "CONNECTED":
      color = "green";
      icon = <IconCheck size={24} />;
      title = t("oauthResult.connectedTitle", { provider: providerLabel });
      description = t("oauthResult.connectedDescription", {
        account: state.externalDisplayLabel,
        provider: providerLabel,
      });
      break;
    case "CANCELLED":
      color = "gray";
      title = t("oauthResult.cancelledTitle", { provider: providerLabel });
      description = t("oauthResult.cancelledDescription", {
        provider: providerLabel,
      });
      break;
    case "PROVIDER_UNAVAILABLE":
      color = "gray";
      title = t("oauthResult.unavailableTitle", { provider: providerLabel });
      description = t(`providerGuidance.${state.status}`, {
        provider: providerLabel,
      });
      break;
    case "FAILED":
      description = t(`oauthResult.failure.${state.reason}`);
      break;
    case "AUTH_REQUIRED":
      color = "blue";
      icon = <IconLock size={24} />;
      title = t("oauthResult.authRequiredTitle");
      description = t("oauthResult.authRequiredDescription");
      break;
  }

  return (
    <Container size="xs" py={{ base: "lg", sm: "xl" }}>
      <Paper
        withBorder
        radius="lg"
        p={{ base: "lg", sm: "xl" }}
        data-testid="external-account-oauth-result"
      >
        <Stack align="center" gap="lg" ta="center">
          <ThemeIcon color={color} variant="light" size="xl" radius="xl">
            {provider === null ? icon : providerIcon(provider)}
          </ThemeIcon>
          <Stack gap={rem(4)}>
            <Title order={1} size="h2">
              {title}
            </Title>
            <Text c="dimmed">{description}</Text>
          </Stack>

          {state.type === "CONNECTED" && state.providerTeamLabel !== null ? (
            <Alert color="green" variant="light" w="100%">
              {t("oauthResult.team", { team: state.providerTeamLabel })}
            </Alert>
          ) : null}

          <Group justify="center" wrap="wrap">
            {state.type === "AUTH_REQUIRED" ? (
              <Button
                component={Link}
                href="/login?next=%2Faccount%2Fexternal-accounts"
              >
                {t("oauthResult.signIn")}
              </Button>
            ) : null}
            {(state.type === "CANCELLED" ||
              (state.type === "FAILED" && state.provider !== null)) &&
            provider !== null ? (
              <Button
                component={Link}
                href={`/account/external-accounts/connect/${provider}`}
                leftSection={<IconExternalLink size={16} />}
              >
                {t("oauthResult.retryProvider", { provider: providerLabel })}
              </Button>
            ) : null}
            {state.type !== "AUTH_REQUIRED" ? (
              <Button
                component={Link}
                href="/account/external-accounts"
                variant={state.type === "CONNECTED" ? "filled" : "default"}
              >
                {t("oauthResult.manage")}
              </Button>
            ) : null}
          </Group>

          {state.type === "AUTH_REQUIRED" ? (
            <Anchor component={Link} href="/account/external-accounts">
              {t("oauthResult.manage")}
            </Anchor>
          ) : null}
        </Stack>
      </Paper>
    </Container>
  );
}
