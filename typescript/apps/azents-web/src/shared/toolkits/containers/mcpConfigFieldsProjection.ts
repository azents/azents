import { z } from "zod/v4";
import { projectMcpConfig } from "../toolkit-config-projection.ts";
import type { McpConfigView } from "../toolkit-config-projection.ts";
import type { McpConfigFieldsProps } from "../types";

const credentialFields = z.object({
  value: z.string().catch(""),
  token: z.string().catch(""),
  client_id: z.string().catch(""),
  client_secret: z.string().catch(""),
});

export interface McpConfigFieldsViewProps {
  configView: McpConfigView;
  credentialsView: z.infer<typeof credentialFields>;
  hasCredentials: boolean;
  testState: McpConfigFieldsProps["testState"];
  onTestConnection: McpConfigFieldsProps["onTestConnection"];
  canTest: boolean;
  onSetConfig: (key: string, value: unknown) => void;
  onSetCredential: (key: string, value: unknown) => void;
  onAuthTypeChange: (value: string | null) => void;
}

/** Decode consumed fields; original provider records remain opaque update transport. */
export function projectMcpConfigFields(
  props: McpConfigFieldsProps,
): McpConfigFieldsViewProps {
  const configView = projectMcpConfig(props.config);
  return {
    configView,
    credentialsView: credentialFields.parse(props.credentials ?? {}),
    hasCredentials: props.hasCredentials,
    testState: props.testState,
    onTestConnection: props.onTestConnection,
    canTest:
      Boolean(configView.server_url) &&
      ("owner" in props || Boolean(props.handle)),
    onSetConfig: (key, value) =>
      props.onConfigChange({ ...props.config, [key]: value }),
    onSetCredential: (key, value) =>
      props.onCredentialsChange({ ...(props.credentials ?? {}), [key]: value }),
    onAuthTypeChange: (value) => {
      const newType = value ?? "none";
      props.onConfigChange({ ...props.config, auth_type: newType });
      props.onCredentialsChange(
        newType === "oauth2" ? null : { type: newType },
      );
    },
  };
}
