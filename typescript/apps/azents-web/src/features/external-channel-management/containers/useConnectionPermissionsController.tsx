"use client";
import { useDisclosure } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import type { ManagedConnection } from "@azents/public-client";
type ConnectionPermissionName =
  | "inbound_events"
  | "thread_history"
  | "post_messages"
  | "update_messages"
  | "delete_messages"
  | "download_files"
  | "upload_files"
  | "customize_messages";
interface ConnectionPermission {
  name: ConnectionPermissionName;
  enabled: boolean;
}
function connectionPermissionEntries(
  connection: ManagedConnection,
): ConnectionPermission[] {
  if (connection.capabilities === null) {
    return [];
  }
  const names =
    connection.provider === "slack"
      ? SLACK_CONNECTION_PERMISSION_NAMES
      : CORE_CONNECTION_PERMISSION_NAMES;
  return names.map((name) => ({
    name,
    enabled: connection.capabilities?.[name] === true,
  }));
}
const CORE_CONNECTION_PERMISSION_NAMES: readonly ConnectionPermissionName[] = [
  "inbound_events",
  "thread_history",
  "post_messages",
  "update_messages",
  "delete_messages",
  "download_files",
  "upload_files",
];
const SLACK_CONNECTION_PERMISSION_NAMES: readonly ConnectionPermissionName[] = [
  ...CORE_CONNECTION_PERMISSION_NAMES,
  "customize_messages",
];
export interface ConnectionPermissionsViewProps {
  connection: {
    connection: ManagedConnection;
  }["connection"];
  t: ReturnType<typeof useTranslations<"workspace.agents.externalChannels">>;
  opened: boolean;
  open: () => void;
  close: () => void;
  permissions: ConnectionPermission[];
  granted: ConnectionPermission[];
  missing: ConnectionPermission[];
}
export function useConnectionPermissionsController({
  connection,
}: {
  connection: ManagedConnection;
}): ConnectionPermissionsViewProps {
  const t = useTranslations("workspace.agents.externalChannels");
  const [opened, { open, close }] = useDisclosure(false);
  const permissions = connectionPermissionEntries(connection);
  const granted = permissions.filter((permission) => permission.enabled);
  const missing = permissions.filter((permission) => !permission.enabled);
  return { connection, t, opened, open, close, permissions, granted, missing };
}
