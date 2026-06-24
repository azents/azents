/**
 * Workspace layout
 *
 * Workspace shell with auth check + membership check + sidebar navigation.
 * Non-members are redirected server-side to /join/{handle}.
 */
import { TRPCError } from "@trpc/server";
import { redirect } from "next/navigation";
import { LoginRequired } from "@/features/auth/components/LoginRequired";
import { WorkspaceShell } from "@/features/workspace/components/WorkspaceShell";
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

  // Server-side membership check — non-member to join request, expired token to login
  try {
    await trpc.workspaceMember.me({ handle });
  } catch (e) {
    if (e instanceof TRPCError) {
      if (e.code === "FORBIDDEN") {
        redirect(`/join/${handle}`);
      }
      if (e.code === "UNAUTHORIZED") {
        redirect(`/login?next=${encodeURIComponent(`/w/${handle}`)}`);
      }
    }
    throw e;
  }

  return <WorkspaceShell handle={handle}>{children}</WorkspaceShell>;
}
