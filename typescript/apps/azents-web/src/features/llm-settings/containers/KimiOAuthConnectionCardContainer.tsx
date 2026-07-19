"use client";

import { KimiOAuthConnectionCard } from "../components/KimiOAuthConnectionCard";
import { useKimiOAuthConnectionContainer } from "./useKimiOAuthConnectionContainer";
import type { KimiOAuthConnectionStatus } from "../components/KimiOAuthConnectionCard";

export interface KimiOAuthConnectionCardContainerProps {
  handle: string;
  canManage: boolean;
  connectionStatus: KimiOAuthConnectionStatus | null;
  reconnect: boolean;
  onConnected?: () => void;
}

export function KimiOAuthConnectionCardContainer({
  handle,
  canManage,
  connectionStatus,
  reconnect,
  onConnected,
}: KimiOAuthConnectionCardContainerProps): React.ReactElement {
  const container = useKimiOAuthConnectionContainer({ handle, onConnected });
  return (
    <KimiOAuthConnectionCard
      canManage={canManage}
      connectionStatus={connectionStatus}
      reconnect={reconnect}
      {...container}
    />
  );
}
