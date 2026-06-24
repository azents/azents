"use client";

/**
 * GitHub PAT section component.
 *
 * Shows GitHub PAT registration state and provides replace/delete on user profile page.
 * Manages GitHub PAT connection status and settings actions internally.
 */

import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconBrandGithub, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type { PatStatus } from "@/features/github-pat-settings/types";

interface GitHubPATSectionProps {
  handle: string;
}

export function GitHubPATSection({
  handle,
}: GitHubPATSectionProps): React.ReactElement {
  const t = useTranslations("memberProfile");
  const utils = trpc.useUtils();

  // Fetch PAT status
  const statusQuery = trpc.githubPat.getStatus.useQuery({ handle });

  const patStatus: PatStatus = useMemo(() => {
    if (statusQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (statusQuery.isError) {
      return { type: "ERROR", message: statusQuery.error.message };
    }

    const data = statusQuery.data;
    if (!data || !data.registered) {
      return { type: "NOT_REGISTERED" };
    }

    return {
      type: "REGISTERED",
      githubUsername: data.github_username ?? "",
      displayHint: data.display_hint ?? null,
      expiresAt: data.expires_at ?? null,
    };
  }, [
    statusQuery.isLoading,
    statusQuery.isError,
    statusQuery.data,
    statusQuery.error,
  ]);

  // Delete mutation
  const deleteMutation = trpc.githubPat.remove.useMutation({
    onSuccess: () => {
      void utils.githubPat.getStatus.invalidate({ handle });
    },
  });

  const handleDelete = useCallback((): void => {
    if (window.confirm(t("githubPatDeleteConfirm"))) {
      deleteMutation.mutate({ handle });
    }
  }, [handle, deleteMutation, t]);

  const setupUrl = `/w/${handle}/settings/github-pat`;

  return (
    <Paper withBorder p="lg" radius="md" mt="lg">
      <Stack gap="md">
        <Title order={4}>{t("githubPat")}</Title>

        {patStatus.type === "LOADING" && <Loader size="sm" />}

        {patStatus.type === "ERROR" && (
          <Text c="red" size="sm">
            {patStatus.message}
          </Text>
        )}

        {patStatus.type === "NOT_REGISTERED" && (
          <Group justify="space-between" align="center">
            <Group gap="sm">
              <IconBrandGithub size={18} />
              <Text size="sm" c="dimmed">
                {t("githubPatNotConnected")}
              </Text>
            </Group>
            <Button component="a" href={setupUrl} variant="light" size="xs">
              {t("githubPatRegister")}
            </Button>
          </Group>
        )}

        {patStatus.type === "REGISTERED" && (
          <Group justify="space-between" wrap="nowrap">
            <Group gap="sm">
              <IconBrandGithub size={18} />
              <Text size="sm">@{patStatus.githubUsername}</Text>
              {patStatus.displayHint && (
                <Text size="xs" c="dimmed">
                  ({patStatus.displayHint}...)
                </Text>
              )}
              <Badge color="green" variant="light" size="sm">
                {t("githubPatConnected")}
              </Badge>
            </Group>
            <Group gap="xs">
              <Button component="a" href={setupUrl} variant="light" size="xs">
                {t("githubPatReplace")}
              </Button>
              <ActionIcon
                variant="subtle"
                color="red"
                size="sm"
                onClick={handleDelete}
                loading={deleteMutation.isPending}
                aria-label={t("githubPatDelete")}
              >
                <IconTrash size={14} />
              </ActionIcon>
            </Group>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}
