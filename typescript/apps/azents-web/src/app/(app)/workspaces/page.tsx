/**
 * Workspace list route
 *
 * Checks authentication status server-side and
 * renders LoginRequired component when unauthenticated.
 */
import { LoginRequired } from "@/features/auth/components/LoginRequired";
import { WorkspacesListPage } from "@/features/workspaces/pages/WorkspacesListPage";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";

export default async function Page(): Promise<React.ReactElement> {
  const authState = await getInitialAuthState();

  if (authState.status !== "authenticated") {
    return <LoginRequired />;
  }

  return <WorkspacesListPage />;
}
