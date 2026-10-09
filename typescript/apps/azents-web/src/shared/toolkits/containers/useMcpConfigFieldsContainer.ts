"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  McpConfigFieldsInput,
  McpConfigFieldsProps,
  ProviderConnectionTestResult,
  ProviderConnectionTestState,
} from "../types";
export function useMcpConfigFieldsContainer(
  props: McpConfigFieldsInput,
): McpConfigFieldsProps {
  const t = useTranslations("workspace.toolkits.mcp");
  const [testState, setTestState] = useState<ProviderConnectionTestState>({
    type: "IDLE",
  });
  const mutation = trpc.toolkit.testConnection.useMutation();
  async function test(): Promise<void> {
    if (!props.handle) {
      return;
    }
    setTestState({ type: "TESTING" });
    try {
      const result = await mutation.mutateAsync({
        handle: props.handle,
        ...(props.agentId != null && { agentId: props.agentId }),
        toolkitType: "mcp",
        toolkitConfigId: props.toolkitConfigId ?? null,
        config: props.config,
        credentials: props.credentials,
      });
      const nextResult: ProviderConnectionTestResult = {
        success: result.success,
        message: result.success
          ? t("testConnectionSuccess")
          : t("testConnectionFailed", { message: result.message }),
      };
      if (result.discovered_auth_url != null) {
        nextResult.discoveredAuthUrl = result.discovered_auth_url;
      }
      if (result.discovered_token_url != null) {
        nextResult.discoveredTokenUrl = result.discovered_token_url;
      }
      if (result.supports_dcr != null) {
        nextResult.supportsDcr = result.supports_dcr;
      }
      setTestState({ type: "RESULT", result: nextResult });
    } catch (error: unknown) {
      setTestState({
        type: "RESULT",
        result: {
          success: false,
          message: t("testConnectionFailed", {
            message: error instanceof Error ? error.message : "Unknown error",
          }),
        },
      });
    }
  }
  return {
    ...props,
    testState,
    onTestConnection: () => {
      void test();
    },
  };
}
