"use client";

import { RuntimeProvidersPageContent } from "./components/RuntimeProvidersPageContent";
import { useRuntimeProvidersPageContainer } from "./containers/useRuntimeProvidersPageContainer";

export function RuntimeProvidersPage(): React.ReactElement {
  const props = useRuntimeProvidersPageContainer();
  return <RuntimeProvidersPageContent {...props} />;
}
