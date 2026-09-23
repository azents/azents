"use client";

import { XaiOAuthConnectionCard } from "../components/XaiOAuthConnectionCard";
import { useXaiOAuthConnectionContainer } from "./useXaiOAuthConnectionContainer";

interface XaiOAuthConnectionCardContainerProps {
  handle: string;
  canManage: boolean;
  integrationId?: string;
  onConnected?: () => void;
}

export function XaiOAuthConnectionCardContainer({
  handle,
  canManage,
  integrationId,
  onConnected,
}: XaiOAuthConnectionCardContainerProps): React.ReactElement {
  const container = useXaiOAuthConnectionContainer({
    handle,
    integrationId,
    onConnected,
  });
  return (
    <XaiOAuthConnectionCard
      canManage={canManage}
      integrationId={integrationId}
      {...container}
    />
  );
}
