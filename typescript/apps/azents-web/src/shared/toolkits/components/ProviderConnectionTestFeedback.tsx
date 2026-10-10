import { Alert, Text } from "@mantine/core";
import { IconAlertTriangle, IconCheck } from "@tabler/icons-react";
import type { ProviderConnectionTestState } from "../types";
import type { ReactElement } from "react";

/** Render every connection-test outcome while retaining provider result markup. */
export function ProviderConnectionTestFeedback({
  state,
  preWrap,
}: {
  state: ProviderConnectionTestState;
  preWrap: boolean;
}): ReactElement | null {
  switch (state.type) {
    case "IDLE":
    case "TESTING":
      return null;
    case "ERROR":
      return (
        <Alert
          variant="light"
          color="red"
          icon={<IconAlertTriangle size={16} />}
        >
          {preWrap ? (
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {state.message}
            </Text>
          ) : (
            state.message
          )}
        </Alert>
      );
    case "RESULT":
      return (
        <Alert
          variant="light"
          color={state.result.success ? "green" : "red"}
          icon={
            state.result.success ? (
              <IconCheck size={16} />
            ) : (
              <IconAlertTriangle size={16} />
            )
          }
        >
          {preWrap ? (
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {state.result.message}
            </Text>
          ) : (
            state.result.message
          )}
        </Alert>
      );
  }
}
