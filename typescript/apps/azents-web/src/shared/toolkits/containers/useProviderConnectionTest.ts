"use client";
import { trpc } from "@/trpc/client";
import type {
  ProviderConnectionTestControl,
  ProviderConnectionTestState,
  ToolkitConfigFieldsInput,
} from "../types";

export function useProviderConnectionTest(
  props: ToolkitConfigFieldsInput,
  toolkitType: string,
): ProviderConnectionTestControl {
  const mutation = trpc.toolkit.testConnection.useMutation();
  const testState: ProviderConnectionTestState = mutation.isPending
    ? { type: "TESTING" }
    : mutation.isSuccess
      ? {
          type: "RESULT",
          result: {
            success: mutation.data.success,
            message: mutation.data.message,
          },
        }
      : mutation.isError
        ? { type: "ERROR", message: mutation.error.message }
        : { type: "IDLE" };
  return {
    testState,
    onTestConnection: () =>
      mutation.mutate({
        handle: props.handle,
        ...(props.agentId != null && { agentId: props.agentId }),
        toolkitType,
        toolkitConfigId: props.toolkitConfigId ?? null,
        config: props.config,
        credentials: props.credentials,
      }),
  };
}
