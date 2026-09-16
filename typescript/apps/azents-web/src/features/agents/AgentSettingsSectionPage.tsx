import { ExternalChannelSettingsPage } from "@/features/external-channel-management/ExternalChannelSettingsPage";
import { AgentAutomaticProjectsPage } from "./AgentAutomaticProjectsPage";
import { AgentMemorySettingsPage } from "./AgentMemorySettingsPage";
import { AgentRuntimeSettingsPage } from "./AgentRuntimeSettingsPage";
import { AgentRuntimeWebServicesPage } from "./AgentRuntimeWebServicesPage";
import { AgentSettingsPage } from "./AgentSettingsPage";
import type { AgentFormSection } from "./components/AgentForm";
import type { AgentResponse } from "@azents/public-client";

export type AgentSettingsSection =
  | AgentFormSection
  | "memory"
  | "runtime"
  | "services"
  | "channels"
  | "projects"
  | "danger";

interface AgentSettingsSectionPageProps {
  handle: string;
  agent: AgentResponse;
  section: AgentSettingsSection;
}

export function AgentSettingsSectionPage({
  handle,
  agent,
  section,
}: AgentSettingsSectionPageProps): React.ReactElement {
  switch (section) {
    case "memory":
      return <AgentMemorySettingsPage handle={handle} agent={agent} />;
    case "runtime":
      return <AgentRuntimeSettingsPage handle={handle} agent={agent} />;
    case "services":
      return <AgentRuntimeWebServicesPage handle={handle} agent={agent} />;
    case "channels":
      return <ExternalChannelSettingsPage handle={handle} agent={agent} />;
    case "projects":
      return <AgentAutomaticProjectsPage handle={handle} agent={agent} />;
    default:
      return (
        <AgentSettingsPage handle={handle} agent={agent} section={section} />
      );
  }
}
