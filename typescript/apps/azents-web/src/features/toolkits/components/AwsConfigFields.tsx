"use client";

/**
 * AWS Toolkit settings form fields.
 *
 * Settings for AWS Managed MCP Server connection.
 * Provides Region, Access Key, Role Assume, Allow Write, and connection test.
 */

import {
  Accordion,
  Alert,
  Button,
  Code,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconCheck,
  IconInfoCircle,
  IconPlugConnected,
  IconSettings,
} from "@tabler/icons-react";
import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";

type AwsConfig = Record<string, unknown>;
type AwsCredentials = Record<string, unknown> | null;

interface AwsConfigFieldsProps {
  config: AwsConfig;
  onConfigChange: (config: AwsConfig) => void;
  credentials: AwsCredentials;
  onCredentialsChange: (credentials: AwsCredentials) => void;
  hasCredentials: boolean;
  handle: string;
  toolkitConfigId?: string;
}

const AWS_REGIONS = [
  { value: "us-east-1", label: "US East (N. Virginia)" },
  { value: "us-east-2", label: "US East (Ohio)" },
  { value: "us-west-1", label: "US West (N. California)" },
  { value: "us-west-2", label: "US West (Oregon)" },
  { value: "ap-northeast-1", label: "Asia Pacific (Tokyo)" },
  { value: "ap-northeast-2", label: "Asia Pacific (Seoul)" },
  { value: "ap-northeast-3", label: "Asia Pacific (Osaka)" },
  { value: "ap-southeast-1", label: "Asia Pacific (Singapore)" },
  { value: "ap-southeast-2", label: "Asia Pacific (Sydney)" },
  { value: "ap-south-1", label: "Asia Pacific (Mumbai)" },
  { value: "eu-central-1", label: "Europe (Frankfurt)" },
  { value: "eu-west-1", label: "Europe (Ireland)" },
  { value: "eu-west-2", label: "Europe (London)" },
  { value: "eu-west-3", label: "Europe (Paris)" },
  { value: "eu-north-1", label: "Europe (Stockholm)" },
  { value: "sa-east-1", label: "South America (São Paulo)" },
  { value: "ca-central-1", label: "Canada (Central)" },
];

export function AwsConfigFields({
  config,
  onConfigChange,
  credentials,
  onCredentialsChange,
  hasCredentials,
  handle,
  toolkitConfigId,
}: AwsConfigFieldsProps): React.ReactElement {
  const region =
    typeof config.region === "string" ? config.region : "us-east-1";
  const roleArn = typeof config.role_arn === "string" ? config.role_arn : "";
  const externalId =
    typeof config.external_id === "string" ? config.external_id : "";
  const timeoutValue = typeof config.timeout === "number" ? config.timeout : 30;

  const accessKeyId = useMemo(
    () =>
      credentials && typeof credentials.access_key_id === "string"
        ? credentials.access_key_id
        : "",
    [credentials],
  );

  const [showKeyInput, setShowKeyInput] = useState(!hasCredentials);

  const testConnectionMutation = trpc.toolkit.testConnection.useMutation();

  const handleTestConnection = useCallback((): void => {
    testConnectionMutation.mutate({
      handle,
      toolkitType: "aws",
      toolkitConfigId: toolkitConfigId ?? null,
      config,
      credentials,
    });
  }, [handle, toolkitConfigId, config, credentials, testConnectionMutation]);

  const iamActions = [
    "aws-mcp:InvokeMcp",
    "aws-mcp:CallReadOnlyTool",
    "aws-mcp:CallReadWriteTool (when write allowed)",
  ];

  return (
    <Stack gap="md">
      <Select
        label="Region"
        description="Default AWS region for API calls"
        data={AWS_REGIONS}
        value={region}
        onChange={(v) =>
          onConfigChange({ ...config, region: v ?? "us-east-1" })
        }
        searchable
        required
      />

      {accessKeyId && !showKeyInput ? (
        <Alert variant="light" color="blue" icon={<IconInfoCircle size={16} />}>
          <Stack gap={4}>
            <Text size="sm">
              Access Key ID: <Code>{accessKeyId}</Code>
            </Text>
            <Button
              size="xs"
              variant="subtle"
              onClick={() => setShowKeyInput(true)}
            >
              Replace Credentials
            </Button>
          </Stack>
        </Alert>
      ) : (
        <Stack gap="xs">
          <TextInput
            label="Access Key ID"
            placeholder="AKIA..."
            required
            value={accessKeyId}
            onChange={(e) =>
              onCredentialsChange({
                ...credentials,
                access_key_id: e.currentTarget.value,
              })
            }
          />
          <PasswordInput
            label="Secret Access Key"
            placeholder="Enter secret access key"
            required
            onChange={(e) =>
              onCredentialsChange({
                ...credentials,
                access_key_id: accessKeyId,
                secret_access_key: e.currentTarget.value,
              })
            }
          />
        </Stack>
      )}

      <Accordion variant="contained">
        <Accordion.Item value="role-assume">
          <Accordion.Control>Role Assume (optional)</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="xs">
              <TextInput
                label="Role ARN"
                placeholder="arn:aws:iam::123456789012:role/MyRole"
                description="Assume this Role with Access Key and call API with temporary credentials"
                value={roleArn}
                onChange={(e) =>
                  onConfigChange({
                    ...config,
                    role_arn: e.currentTarget.value || null,
                  })
                }
              />
              <TextInput
                label="External ID"
                placeholder="Optional external ID"
                description="Additional security for cross-account AssumeRole"
                value={externalId}
                onChange={(e) =>
                  onConfigChange({
                    ...config,
                    external_id: e.currentTarget.value || null,
                  })
                }
              />
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      <Alert
        variant="light"
        color="blue"
        icon={<IconInfoCircle size={16} />}
        title="Required IAM Permissions"
      >
        <Text size="xs" mb="xs">
          Grant these permissions to your IAM user
          {roleArn ? " or the assumed role" : ""}:
        </Text>
        <Stack gap={2}>
          {iamActions.map((action) => (
            <Text key={action} size="xs">
              <Code>{action}</Code>
            </Text>
          ))}
          <Text size="xs" c="dimmed" mt="xs">
            + actual AWS API permissions (e.g., cloudwatch:GetMetricData,
            ce:GetCostAndUsage, ec2:DescribeInstances)
          </Text>
        </Stack>
      </Alert>

      <Stack gap="xs">
        <Button
          variant="light"
          leftSection={<IconPlugConnected size={16} />}
          onClick={handleTestConnection}
          loading={testConnectionMutation.isPending}
          disabled={!credentials}
        >
          Test Connection
        </Button>

        {testConnectionMutation.isSuccess && (
          <Alert
            variant="light"
            color={testConnectionMutation.data.success ? "green" : "red"}
            icon={
              testConnectionMutation.data.success ? (
                <IconCheck size={16} />
              ) : (
                <IconAlertTriangle size={16} />
              )
            }
          >
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {testConnectionMutation.data.message}
            </Text>
          </Alert>
        )}
      </Stack>

      <Accordion variant="contained">
        <Accordion.Item value="advanced">
          <Accordion.Control icon={<IconSettings size={16} />}>
            Advanced Settings
          </Accordion.Control>
          <Accordion.Panel>
            <NumberInput
              label="Timeout (seconds)"
              description="MCP tool call timeout. Default 30 seconds."
              value={timeoutValue}
              onChange={(v) => onConfigChange({ ...config, timeout: v })}
              min={1}
              max={300}
            />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}
