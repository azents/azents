"use client";
import {
  Badge,
  Center,
  Container,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconLock, IconMail } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { ElevationView } from "../../../shared/elevation/components/ElevationView";
import { useElevationRequiredViewController } from "../containers/useElevationRequiredViewController";
import { PasswordForm } from "./PasswordForm";
import type { ElevationRequiredViewViewProps } from "../containers/useElevationRequiredViewController";
import type { SecurityContainerProps } from "../containers/useSecurityContainer";
/**
 * Security settings UI.
 *
 * Authentication method list display + password management.
 * Show modal when elevation is required.
 */
import type { AuthMethod } from "@azents/public-client";

export function Security({
  state,
  passwordState,
  passwordResetKey,
  onSetPassword,
  onElevated,
}: SecurityContainerProps): React.ReactElement {
  const t = useTranslations("security");

  switch (state.type) {
    case "LOADING":
      return (
        <Center py="xl">
          <Loader />
        </Center>
      );
    case "ELEVATION_REQUIRED":
      return (
        <ElevationRequiredView
          elevationMethods={state.elevationMethods}
          onElevated={onElevated}
        />
      );
    case "ERROR":
      return (
        <Center py="xl">
          <Text c="red">{state.message}</Text>
        </Center>
      );
    case "LOADED":
      return (
        <Container size="sm" py="xl">
          <Title order={2} mb="lg">
            {t("headline")}
          </Title>

          {/* Authentication method list */}
          <Paper withBorder p="lg" radius="md" mb="lg">
            <Title order={4} mb="md">
              {t("authMethods")}
            </Title>
            <Stack gap="sm">
              {state.methods.map((method) => (
                <Group key={method.type} gap="sm">
                  {method.type === "email" ? (
                    <IconMail size={18} />
                  ) : (
                    <IconLock size={18} />
                  )}
                  <Text size="sm">
                    {method.type === "email"
                      ? t("methodEmail")
                      : t("methodPassword")}
                  </Text>
                  <Badge
                    variant="light"
                    color={method.enabled ? "green" : "gray"}
                    size="sm"
                  >
                    {method.enabled ? t("enabled") : t("disabled")}
                  </Badge>
                </Group>
              ))}
            </Stack>
          </Paper>

          {/* Password management */}
          <Paper withBorder p="lg" radius="md">
            <Title order={4} mb="md">
              {t("passwordSection")}
            </Title>
            <PasswordForm
              key={passwordResetKey}
              hasPassword={state.hasPassword}
              state={passwordState}
              onSetPassword={onSetPassword}
            />
          </Paper>
        </Container>
      );
  }
}

/** Elevation required view — rendered directly in main view */
function ElevationRequiredView(props: {
  elevationMethods: AuthMethod[] | null;
  onElevated: () => void;
}): React.ReactElement {
  return (
    <ElevationRequiredViewView {...useElevationRequiredViewController(props)} />
  );
}

export function ElevationRequiredViewView({
  elevation,
}: ElevationRequiredViewViewProps): React.ReactElement {
  return <ElevationView {...elevation} />;
}
