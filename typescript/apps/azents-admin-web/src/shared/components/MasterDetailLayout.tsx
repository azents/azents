"use client";

/**
 * 반응형 Master-Detail 레이아웃.
 *
 * 데스크톱: CSS Grid 2컬럼 (master + detail), height 100%, overflow auto
 * 모바일: master만 표시, detail은 Drawer로 오버레이
 *
 * azents admin-web의 레이아웃 패턴을 따름.
 */
import { Box, Drawer, Paper } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";

interface MasterDetailLayoutProps {
  master: React.ReactNode;
  detail: React.ReactNode;
  detailOpen: boolean;
  onDetailClose: () => void;
}

export function MasterDetailLayout({
  master,
  detail,
  detailOpen,
  onDetailClose,
}: MasterDetailLayoutProps): React.ReactElement {
  // Mantine md breakpoint = 62em = 992px
  // SSR 기본값을 true로 설정하여 레이아웃 시프트 방지
  const isDesktop = useMediaQuery("(min-width: 62em)", true);

  if (isDesktop) {
    return (
      <Box
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "var(--mantine-spacing-md)",
          height: "100%",
        }}
      >
        <Paper
          withBorder
          style={{ overflow: "auto", minHeight: 0, height: "100%" }}
        >
          {master}
        </Paper>
        <Paper
          withBorder
          style={{ overflow: "auto", minHeight: 0, height: "100%" }}
        >
          {detail}
        </Paper>
      </Box>
    );
  }

  // 모바일: master만 표시, detail은 Drawer
  return (
    <>
      <Box h="100%">{master}</Box>
      <Drawer
        opened={detailOpen}
        onClose={onDetailClose}
        position="bottom"
        size="100%"
        withCloseButton
      >
        {detail}
      </Drawer>
    </>
  );
}
