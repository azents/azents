/**
 * Workspace route membership gate.
 *
 * The visual shell is selected by child route groups:
 * - (workspace) keeps the workspace-wide navigation shell.
 * - (agent) uses the Agent-focused shell.
 */
import { TRPCError } from "@trpc/server";
import { redirect } from "next/navigation";
import { LoginRequired } from "@/shared/auth/components/LoginRequired";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";
import { trpc } from "@/trpc/server";

export default async function WorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const authState = await getInitialAuthState();

  if (authState.status !== "authenticated") {
    return <LoginRequired />;
  }

  const { handle } = await params;

  try {
    await trpc.workspaceMember.me({ handle });
  } catch (e) {
    if (e instanceof TRPCError) {
      if (e.code === "FORBIDDEN") {
        redirect(`/join/${handle}`);
      }
      if (e.code === "UNAUTHORIZED") {
        // The browser knows the selected child path and query; the layout does not.
        return <LoginRequired />;
      }
    }
    throw e;
  }

  return <>{children}</>;
}
