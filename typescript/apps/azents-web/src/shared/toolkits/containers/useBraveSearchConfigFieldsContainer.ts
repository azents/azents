"use client";

/** Connect the Brave Search settings view to the existing Toolkit test mutation. */

import { useState } from "react";
import { normalizeCredentialEdits } from "@/shared/lib/redacted-credentials";
import { trpc } from "@/trpc/client";
import {
  braveFieldCallbacks,
  projectBraveFormFields,
} from "../provider-form-fields";
import { pickToolkitOwnerScope } from "../toolkit-owner-scope";

import type { BraveSearchFieldsViewProps } from "../components/BraveSearchFieldsView";
import type { ToolkitConfigFieldsInput } from "../types";

export type BraveSearchConfigFieldsProps = ToolkitConfigFieldsInput;

export function useBraveSearchConfigFieldsContainer(
  props: BraveSearchConfigFieldsProps,
): BraveSearchFieldsViewProps {
  const {
    config,
    onConfigChange,
    credentials,
    onCredentialsChange,
    hasCredentials,
    toolkitConfigId,
  } = props;
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

  return {
    fields: projectBraveFormFields(config, credentials),
    ...braveFieldCallbacks(
      config,
      (nextConfig) => {
        testConnection.reset();
        onConfigChange(nextConfig);
      },
      (nextCredentials) => {
        testConnection.reset();
        onCredentialsChange(nextCredentials);
      },
    ),
    hasCredentials,
    replacingKey,
    onReplaceKey: () => setReplacingKey(true),
    onTestConnection: () =>
      testConnection.mutate({
        ...pickToolkitOwnerScope(props),
        toolkitType: "brave_search",
        toolkitConfigId: toolkitConfigId ?? null,
        config,
        credentials: normalizeCredentialEdits(credentials),
      }),
    testState,
  };
}
