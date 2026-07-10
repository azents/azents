"use client";

/**
 * Provider-specific setup guide.
 *
 * Guides setup for API Key, AWS Bedrock, and Google Vertex AI providers.
 */

import { Button, Code, Collapse, Stack, Text } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconHelp } from "@tabler/icons-react";
import { useTranslations } from "next-intl";

export type CredentialType =
  | "api_key"
  | "aws_credentials"
  | "gcp_service_account";

export function SetupGuide({
  credType,
  provider,
}: {
  credType: CredentialType;
  provider: string;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings");
  const [opened, { toggle }] = useDisclosure(false);

  return (
    <Stack gap="xs">
      <Button
        variant="subtle"
        size="compact-sm"
        leftSection={<IconHelp size={14} />}
        onClick={toggle}
        styles={{ root: { alignSelf: "flex-start" } }}
      >
        {t("setupGuideToggle")}
      </Button>
      <Collapse expanded={opened}>
        <Stack
          gap="xs"
          p="sm"
          style={{
            backgroundColor: "var(--mantine-color-default)",
            borderRadius: "var(--mantine-radius-sm)",
            border: "1px solid var(--mantine-color-default-border)",
          }}
        >
          {credType === "api_key" && (
            <Text size="sm" c="dimmed">
              {provider === "xai"
                ? t("setupGuideXaiApiKey")
                : t("setupGuideApiKey")}
            </Text>
          )}
          {credType === "aws_credentials" && (
            <>
              <Text size="sm" fw={500}>
                {t("setupGuideAwsTitle")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("setupGuideAwsStep1")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("setupGuideAwsStep2")}
              </Text>
              <Code block>
                {JSON.stringify(
                  {
                    Version: "2012-10-17",
                    Statement: [
                      {
                        Effect: "Allow",
                        Action: [
                          "bedrock:InvokeModel",
                          "bedrock:InvokeModelWithResponseStream",
                        ],
                        Resource: "*",
                      },
                      {
                        Effect: "Allow",
                        Action: [
                          "aws-marketplace:ViewSubscriptions",
                          "aws-marketplace:Subscribe",
                        ],
                        Resource: "*",
                      },
                    ],
                  },
                  null,
                  2,
                )}
              </Code>
              <Text size="sm" c="dimmed">
                {t("setupGuideAwsStep3")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("setupGuideAwsStep4")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("setupGuideAwsRoleAssume")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("setupGuideAwsStep5")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("setupGuideAwsStep6")}
              </Text>
            </>
          )}
          {credType === "gcp_service_account" && (
            <>
              <Text size="sm" fw={500}>
                {t("setupGuideGcpTitle")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("setupGuideGcpStep1")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("setupGuideGcpStep2")}
              </Text>
              <Code>{t("setupGuideGcpRole")}</Code>
              <Text size="sm" c="dimmed">
                {t("setupGuideGcpStep3")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("setupGuideGcpStep4")}
              </Text>
            </>
          )}
        </Stack>
      </Collapse>
    </Stack>
  );
}
