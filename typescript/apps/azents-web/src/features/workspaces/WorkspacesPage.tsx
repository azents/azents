import { LoginRequired } from "@/features/auth/components/LoginRequired";
import { WorkspacesListPage } from "./pages/WorkspacesListPage";

interface WorkspacesPageProps {
  authenticated: boolean;
}

export function WorkspacesPage({
  authenticated,
}: WorkspacesPageProps): React.ReactElement {
  return authenticated ? <WorkspacesListPage /> : <LoginRequired />;
}
