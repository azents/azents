"use client";

/**
 * Responsive master-detail layout.
 *
 * Desktop: two-column CSS Grid with independently scrolling panels.
 * Mobile: master panel with the detail rendered in a full-screen Drawer.
 */
import { Box, Drawer } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";

interface MasterDetailLayoutProps {
  master: React.ReactNode;
  detail: React.ReactNode;
  detailOpen: boolean;
  onDetailClose: () => void;
  /** CSS grid-template-columns value. */
  columns?: string;
  /** Additional styles for the root container. */
  style?: React.CSSProperties;
}

export function MasterDetailLayout({
  master,
  detail,
  detailOpen,
  onDetailClose,
  columns = "minmax(0, 1fr) minmax(0, 1fr)",
  style,
}: MasterDetailLayoutProps): React.ReactElement {
  // Mantine's md breakpoint is 62em. Default to desktop during SSR to avoid
  // shifting an already-wide layout after hydration.
  const isDesktop = useMediaQuery("(min-width: 62em)", true);

  if (isDesktop) {
    return (
      <Box
        style={{
          display: "grid",
          gridTemplateColumns: columns,
          height: "100%",
          minWidth: 0,
          ...style,
        }}
      >
        <Box
          style={{
            overflow: "auto",
            minWidth: 0,
            minHeight: 0,
            height: "100%",
            borderRight: "1px solid var(--mantine-color-default-border)",
          }}
        >
          {master}
        </Box>
        <Box
          style={{
            overflow: "auto",
            minWidth: 0,
            minHeight: 0,
            height: "100%",
          }}
        >
          {detail}
        </Box>
      </Box>
    );
  }

  return (
    <Box style={{ height: "100%", ...style }}>
      <Box style={{ overflow: "auto", height: "100%" }}>{master}</Box>
      <Drawer
        opened={detailOpen}
        onClose={onDetailClose}
        position="bottom"
        size="100%"
        title="Details"
        withCloseButton
      >
        {detail}
      </Drawer>
    </Box>
  );
}
