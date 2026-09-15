/**
 * Workspace list route
 *
 * Checks authentication status server-side and delegates presentation to the
 * feature page.
 */
import { WorkspacesPage } from "@/features/workspaces/WorkspacesPage";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";

export default async function Page(): Promise<React.ReactElement> {
  const authState = await getInitialAuthState();

  return (
    <WorkspacesPage authenticated={authState.status === "authenticated"} />
  );
}
