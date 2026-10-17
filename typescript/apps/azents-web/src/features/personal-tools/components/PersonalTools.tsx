"use client";

import {
  Alert,
  Badge,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Modal,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
import {
  ToolkitCard,
  ToolkitCollection,
} from "@/shared/toolkits/components/ToolkitCollection";
import type { PersonalToolsProps } from "../containers/usePersonalToolsContainer";

export function PersonalTools({
  handle,
  state,
  pending,
  error,
  deleteTarget,
  testResult,
  onReload,
  onDelete,
  onConfirmDelete,
  onToggle,
  onTest,
}: PersonalToolsProps): React.ReactElement {
  const t = useTranslations("account.personalTools");
  return (
    <Container size="lg" py="xl">
      <Stack>
        <Group justify="space-between">
          <Title order={2}>{t("title")}</Title>
          <Button
            component={Link}
            href={`/w/${encodeURIComponent(handle)}/personal-tools/new`}
          >
            {t("add")}
          </Button>
        </Group>
        <Text size="sm" c="dimmed">
          {t("description")}
        </Text>
        {error && <Alert color="red">{t("operationError")}</Alert>}
        {testResult && (
          <Alert
            color={testResult.success ? "green" : "red"}
            title={t("testResult")}
            role="status"
          >
            {testResult.message}
          </Alert>
        )}
        {state.type === "LOADING" && (
          <Center p="xl">
            <Loader aria-label={t("loading")} />
          </Center>
        )}
        {state.type === "ERROR" && (
          <Alert color="red" title={t("loadError")}>
            <Button variant="subtle" onClick={onReload}>
              {t("reload")}
            </Button>
          </Alert>
        )}
        {state.type === "READY" &&
          (state.items.length === 0 ? (
            <Text py="xl" c="dimmed">
              {t("empty")}
            </Text>
          ) : (
            <ToolkitCollection>
              {state.items.map((toolkit) => (
                <ToolkitCard
                  key={toolkit.id}
                  name={toolkit.name}
                  toolkitType={toolkit.toolkit_type}
                  description={toolkit.description}
                  badges={
                    <Group gap="xs">
                      <Badge variant="light">{toolkit.toolkit_type}</Badge>
                      <Badge
                        variant="dot"
                        color={toolkit.readiness === "ready" ? "green" : "gray"}
                      >
                        {t(
                          toolkit.readiness === "ready"
                            ? "ready"
                            : toolkit.readiness === "disabled"
                              ? "disabled"
                              : "authorizationRequired",
                        )}
                      </Badge>
                      <Badge variant="default">
                        {t(
                          toolkit.access_mode === "all"
                            ? "allowAll"
                            : "selected",
                        )}
                      </Badge>
                    </Group>
                  }
                  control={
                    <Switch
                      checked={toolkit.enabled}
                      disabled={pending}
                      aria-label={t("enabledFor", { name: toolkit.name })}
                      onChange={(event) =>
                        onToggle(toolkit, event.currentTarget.checked)
                      }
                    />
                  }
                  actions={
                    <>
                      <Button
                        component={Link}
                        href={`/w/${encodeURIComponent(handle)}/personal-tools/${encodeURIComponent(toolkit.id)}/edit`}
                        variant="default"
                        size="xs"
                      >
                        {t("edit")}
                      </Button>
                      <Button
                        component={Link}
                        href={`/w/${encodeURIComponent(handle)}/personal-tools/${encodeURIComponent(toolkit.id)}/access`}
                        variant="default"
                        size="xs"
                      >
                        {t("accessTitle")}
                      </Button>
                      <Button
                        variant="subtle"
                        size="xs"
                        disabled={pending}
                        onClick={() => onTest(toolkit)}
                      >
                        {t("test")}
                      </Button>
                      <Button
                        variant="subtle"
                        color="red"
                        size="xs"
                        disabled={pending}
                        onClick={() => onDelete(toolkit)}
                      >
                        {t("delete")}
                      </Button>
                    </>
                  }
                />
              ))}
            </ToolkitCollection>
          ))}
      </Stack>
      <Modal
        opened={deleteTarget !== null}
        onClose={() => onDelete(null)}
        title={t("deleteTitle")}
        closeOnClickOutside={!pending}
        closeOnEscape={!pending}
        withCloseButton={!pending}
        centered
      >
        <Stack>
          <Text style={{ overflowWrap: "anywhere" }}>
            {t("deleteExplanation", { name: deleteTarget?.name ?? "" })}
          </Text>
          {error && <Alert color="red">{t("operationError")}</Alert>}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => onDelete(null)}
              disabled={pending}
            >
              {t("cancel")}
            </Button>
            <Button color="red" onClick={onConfirmDelete} loading={pending}>
              {t("delete")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Container>
  );
}
