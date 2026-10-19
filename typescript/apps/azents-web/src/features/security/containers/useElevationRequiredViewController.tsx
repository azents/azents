"use client";
import { useElevationModal } from "../../../shared/elevation/containers/useElevationModal";
import type { ElevationModalContainerProps } from "../../../shared/elevation/containers/useElevationModal";
import type { AuthMethod } from "@azents/public-client";

function createEmailFallbackMethod(): AuthMethod {
  return {
    type: "email",
    enabled: true,
    configured: true,
    valid: true,
    can_login: true,
    can_elevate: true,
    can_remove: false,
    unavailable_reason: null,
  };
}
export interface ElevationRequiredViewViewProps {
  elevation: ElevationModalContainerProps;
}
export function useElevationRequiredViewController({
  elevationMethods,
  onElevated,
}: {
  elevationMethods: AuthMethod[] | null;
  onElevated: () => void;
}): ElevationRequiredViewViewProps {
  /** Use auth methods fetched from server; show only email while loading */
  const methods = elevationMethods ?? [createEmailFallbackMethod()];
  const elevation = useElevationModal(methods, onElevated);
  return { elevation };
}
