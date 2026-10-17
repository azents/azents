/**
 * Workspace layout.
 *
 * Workspace shell with sidebar navigation. Agent detail routes live in the
 * sibling (agent) group so they can use a focused chat shell instead.
 */
import { WorkspaceComposition } from "./WorkspaceComposition";

export default async function WorkspaceShellLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return (
    <WorkspaceComposition handle={handle}>{children}</WorkspaceComposition>
  );
}
