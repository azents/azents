/**
 * Agent detail layout.
 *
 * Uses the focused Agent shell instead of the workspace-wide sidebar. The shell
 * owns Agent navigation and session list while child screens render their
 * header/content directly.
 */
import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentFocusedShell } from "@/features/agents/components/AgentFocusedShell";
import { trpc } from "@/trpc/server";
import type { ReactNode } from "react";

export default async function AgentDetailLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ handle: string; agentId: string }>;
}): Promise<React.ReactElement> {
  const { handle, agentId } = await params;
  try {
    const agent = await trpc.agent.get({ handle, agentId });
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          height: "calc(100dvh - var(--app-shell-header-offset, 0px))",
          minHeight: 0,
          overflow: "hidden",
        }}
      >
        <AgentFocusedShell handle={handle} agent={agent}>
          {children}
        </AgentFocusedShell>
      </div>
    );
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") {
      notFound();
    }
    throw e;
  }
}
