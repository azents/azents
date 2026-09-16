import { ExternalAccountOAuthResult } from "./components/ExternalAccountOAuthResult";
import type { ExternalAccountOAuthResultState } from "./types";

interface ExternalAccountOAuthPageProps {
  state: ExternalAccountOAuthResultState;
}

export function ExternalAccountOAuthPage({
  state,
}: ExternalAccountOAuthPageProps): React.ReactElement {
  return <ExternalAccountOAuthResult state={state} />;
}
