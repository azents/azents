import {
  Button,
  CopyButton,
  Group,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { IconCheck, IconCopy } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { GitHubWizardAvailability } from "../github-wizard-state";

export function GitHubWizardCallbackHelp({
  availability,
  optional,
}: {
  availability: GitHubWizardAvailability;
  optional: boolean;
}): React.ReactElement {
  const t = useTranslations("workspace.toolkits.github.wizard");
  const g = useTranslations("workspace.toolkits.github");
  const url = availability.type === "READY" ? availability.callbackUrl : null;
  return (
    <Stack gap="xs">
      <Text size="sm" fw={500}>
        {optional ? t("optionalCallbackLabel") : g("callbackLabel")}
      </Text>
      {url != null ? (
        <>
          <TextInput
            aria-label={
              optional ? t("optionalCallbackLabel") : g("callbackLabel")
            }
            readOnly
            value={url}
          />
          <Group justify="flex-start">
            <CopyButton value={url}>
              {({ copied, copy }) => (
                <Button
                  size="xs"
                  variant="default"
                  leftSection={
                    copied ? <IconCheck size="1em" /> : <IconCopy size="1em" />
                  }
                  onClick={copy}
                >
                  {t(copied ? "callbackCopied" : "copyCallback")}
                </Button>
              )}
            </CopyButton>
          </Group>
        </>
      ) : (
        <Text size="sm" c="dimmed">
          {availability.type === "READY"
            ? g("callbackUnavailable")
            : g("availabilityLoading")}
        </Text>
      )}
      {optional && (
        <Text size="xs" c="dimmed">
          {t("optionalCallbackHint")}
        </Text>
      )}
    </Stack>
  );
}
