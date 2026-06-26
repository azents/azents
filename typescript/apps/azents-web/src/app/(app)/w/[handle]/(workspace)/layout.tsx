/**
 * Workspace layout.
 *
 * Workspace shell with sidebar navigation. Agent detail routes live in the
 * sibling (agent) group so they can use a focused chat shell instead.
 */
import { WorkspaceShell } from "@/features/workspace/components/WorkspaceShell";

export default async function WorkspaceShellLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <WorkspaceShell handle={handle}>{children}</WorkspaceShell>;
}
