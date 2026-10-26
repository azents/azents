"use client";

import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import type { AgentBrowserChoiceProps } from "../browserChoiceTypes";

export function AgentBrowserChoice({
  state,
  onSelect,
  onCancel,
  onConfirm,
  onRetry,
  onRefresh,
}: AgentBrowserChoiceProps): React.ReactElement {
  const t = useTranslations("workspace.agents.runtimeSettings.browserChoice");
  switch (state.type) {
    case "LOADING":
      return (
        <Paper withBorder radius="lg" p="lg">
          <Loader size="sm" />
        </Paper>
      );
    case "ERROR":
      return (
        <Alert color="red" title={t("loadError")}>
          <Stack gap="sm">
            <Text size="sm">{state.message}</Text>
            <Button variant="default" onClick={onRefresh}>
              {t("refresh")}
            </Button>
          </Stack>
        </Alert>
      );
    case "READY": {
      const { configuration, browserEnabled, readOnly, saving, confirmation } =
        state;
      const controlsDisabled = !browserEnabled || readOnly || saving;
      return (
        <>
          <Paper withBorder radius="lg" p="lg">
            <Stack gap="sm">
              <Select
                label={t("label")}
                value={configuration.requested}
                allowDeselect={false}
                disabled={controlsDisabled}
                data={[
                  { value: "patchright", label: t("patchright") },
                  { value: "camoufox", label: t("camoufox") },
                ]}
                onChange={(value): void => {
                  if (value === "patchright" || value === "camoufox") {
                    onSelect(value);
                  }
                }}
              />
              {browserEnabled && saving ? (
                <Text size="sm" role="status">
                  {t("saving")}
                </Text>
              ) : null}
              {browserEnabled &&
              !saving &&
              configuration.state === "applying" ? (
                <Text size="sm" role="status">
                  {t("applying", {
                    browser:
                      configuration.requested === "camoufox"
                        ? "Camoufox"
                        : "Patchright",
                  })}
                </Text>
              ) : null}
              {browserEnabled && configuration.state === "offline" ? (
                <Text c="dimmed" size="sm">
                  {t("offline")}
                </Text>
              ) : null}
              {browserEnabled && configuration.state === "failed" ? (
                <Alert color="red" title={t("failedTitle")}>
                  <Stack gap="sm">
                    <Text size="sm">
                      {t(
                        configuration.reason_code ===
                          "browser_configuration_unsupported"
                          ? "unsupported"
                          : "failedDescription",
                      )}
                    </Text>
                    <Group>
                      <Button
                        variant="light"
                        disabled={controlsDisabled}
                        onClick={onRetry}
                      >
                        {t("retry")}
                      </Button>
                      <Button variant="subtle" onClick={onRefresh}>
                        {t("refresh")}
                      </Button>
                    </Group>
                  </Stack>
                </Alert>
              ) : null}
              {browserEnabled && state.error ? (
                <Alert color="red">{state.error}</Alert>
              ) : null}
            </Stack>
          </Paper>
          <Modal
            centered
            opened={browserEnabled && confirmation !== null && !readOnly}
            title={t("confirmTitle")}
            closeOnClickOutside={!saving}
            closeOnEscape={!saving}
            withCloseButton={!saving}
            onClose={onCancel}
          >
            <Stack gap="md">
              <Text size="sm">
                {t("confirmDescription", {
                  browser:
                    confirmation === "camoufox" ? "Camoufox" : "Patchright",
                })}
              </Text>
              <Text c="dimmed" size="sm">
                {t("profiles")}
              </Text>
              <Group justify="flex-end">
                <Button variant="default" disabled={saving} onClick={onCancel}>
                  {t("cancel")}
                </Button>
                <Button loading={saving} onClick={onConfirm}>
                  {t("confirm")}
                </Button>
              </Group>
            </Stack>
          </Modal>
        </>
      );
    }
  }
}
