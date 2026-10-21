"use client";

/**
 * Workspace join request UI component
 *
 * Shows invitation accept/decline and join request submission UI to non-members.
 */
import {
  Alert,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { IconCheck, IconSend } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceJoinViewController } from "../containers/useWorkspaceJoinViewController";
import type { WorkspaceJoinViewOutput } from "../containers/useWorkspaceJoinViewController";

export const WorkspaceJoinView = createReactContainer(
  "WorkspaceJoinView",
  useWorkspaceJoinViewController,
  WorkspaceJoinContent,
);

export function WorkspaceJoinContent({
  handle,
  state,
  message,
  setMessage,
  submitMessage,
  onAcceptInvitation,
  onDeclineInvitation,
}: WorkspaceJoinViewOutput): React.ReactElement {
  const t = useTranslations("workspace.join");

  return (
    <Container size="xs" py="xl">
      <Stack gap="lg" align="center">
        <Title order={2}>{t("title", { workspaceName: handle })}</Title>

        {state.type === "LOADING" && (
          <Center py="xl">
            <Loader size="md" />
          </Center>
        )}

        {state.type === "PENDING_INVITATION" && (
          <Stack gap="md" align="center">
            <Alert color="blue" w="100%">
              {t("pendingInvitation")}
            </Alert>
            <Group>
              <Button color="green" onClick={onAcceptInvitation}>
                {t("acceptInvitation")}
              </Button>
              <Button
                variant="subtle"
                color="red"
                onClick={onDeclineInvitation}
              >
                {t("declineInvitation")}
              </Button>
            </Group>
          </Stack>
        )}

        {state.type === "PENDING_REQUEST" && (
          <Alert color="yellow" w="100%">
            {t("pendingRequest")}
          </Alert>
        )}

        {state.type === "IDLE" && (
          <Stack gap="md" w="100%">
            <Text size="sm" c="dimmed" ta="center">
              {t("requestToJoin")}
            </Text>
            <Textarea
              placeholder={t("messagePlaceholder")}
              value={message}
              onChange={(e) => setMessage(e.currentTarget.value)}
              minRows={3}
            />
            <Button
              leftSection={<IconSend size={16} />}
              onClick={submitMessage}
            >
              {t("submitRequest")}
            </Button>
          </Stack>
        )}

        {state.type === "SUBMITTING" && (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        )}

        {state.type === "SUBMITTED" && (
          <Alert color="green" icon={<IconCheck size={16} />} w="100%">
            {t("requestSent")}
          </Alert>
        )}

        {state.type === "ERROR" && (
          <Alert color="red" w="100%">
            {t("requestError")}
          </Alert>
        )}
      </Stack>
    </Container>
  );
}
