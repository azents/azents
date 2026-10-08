"use client";

/** Connect the Brave Search settings view to the existing Toolkit test mutation. */

import { useState } from "react";
import { normalizeCredentialEdits } from "@/shared/lib/redacted-credentials";
import { trpc } from "@/trpc/client";
import { BraveSearchFieldsView } from "./BraveSearchFieldsView";
import type { BraveSearchFieldsViewProps } from "./BraveSearchFieldsView";

interface BraveSearchConfigFieldsProps {
  config: Record<string, unknown>;
  onConfigChange: (config: Record<string, unknown>) => void;
  credentials: Record<string, unknown> | null;
  onCredentialsChange: (credentials: Record<string, unknown> | null) => void;
  hasCredentials: boolean;
  handle: string;
  agentId?: string;
  toolkitConfigId?: string;
}

export function BraveSearchConfigFields({
  config,
  onConfigChange,
  credentials,
  onCredentialsChange,
  hasCredentials,
  handle,
  agentId,
  toolkitConfigId,
}: BraveSearchConfigFieldsProps): React.ReactElement {
  const [replacingKey, setReplacingKey] = useState(false);
  const testConnection = trpc.toolkit.testConnection.useMutation();
  const testState: BraveSearchFieldsViewProps["testState"] =
    testConnection.isPending
      ? { type: "TESTING" }
      : testConnection.isSuccess
        ? testConnection.data.success
          ? { type: "SUCCESS", message: testConnection.data.message }
          : { type: "FAILURE", message: testConnection.data.message }
        : testConnection.isError
          ? { type: "FAILURE", message: testConnection.error.message }
          : { type: "IDLE" };

  return (
    <BraveSearchFieldsView
      config={config}
      onConfigChange={(nextConfig) => {
        testConnection.reset();
        onConfigChange(nextConfig);
      }}
      credentials={credentials}
      onCredentialsChange={(nextCredentials) => {
        testConnection.reset();
        onCredentialsChange(nextCredentials);
      }}
      hasCredentials={hasCredentials}
      replacingKey={replacingKey}
      onReplaceKey={() => setReplacingKey(true)}
      onTestConnection={() =>
        testConnection.mutate({
          handle,
          ...(agentId != null && { agentId }),
          toolkitType: "brave_search",
          toolkitConfigId: toolkitConfigId ?? null,
          config,
          credentials: normalizeCredentialEdits(credentials),
        })
      }
      testState={testState}
    />
  );
}
