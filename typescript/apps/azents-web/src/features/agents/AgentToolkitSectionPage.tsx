"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { LegacyAgentToolkitSection } from "./components/AgentToolkitSection";
import { ManagedAgentToolkitSectionView } from "./components/ManagedAgentToolkitSection";
import { useAgentToolkitManagementContainer } from "./containers/useAgentToolkitManagementContainer";
import { useLegacyAgentToolkitSection } from "./containers/useLegacyAgentToolkitSection";
import type { AgentToolkitSectionIdentity } from "./types";

const LegacySection = createReactContainer(
  "LegacyAgentToolkitSection",
  useLegacyAgentToolkitSection,
  LegacyAgentToolkitSection,
);
const ManagedSection = createReactContainer(
  "ManagedAgentToolkitSection",
  useAgentToolkitManagementContainer,
  ManagedAgentToolkitSectionView,
);

export function AgentToolkitSectionPage({
  managementAvailable,
  ...identity
}: AgentToolkitSectionIdentity & {
  managementAvailable: boolean;
}): React.ReactElement {
  return managementAvailable ? (
    <ManagedSection {...identity} />
  ) : (
    <LegacySection {...identity} />
  );
}
