/**
 * Agent detail layout.
 *
 * Only provides fixed viewport shell so Agent detail child screens can
 * compose header and content directly.
 */
import type { ReactNode } from "react";

export default function AgentDetailLayout({
  children,
}: {
  children: ReactNode;
}): React.ReactElement {
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
      {children}
    </div>
  );
}
