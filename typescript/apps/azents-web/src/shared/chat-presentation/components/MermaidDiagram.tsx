"use client";
import { Box, Text } from "@mantine/core";
import * as React from "react";

import { useMermaidDiagramController } from "../containers/useMermaidDiagramController";
import { ChatCopyButton } from "./ChatCopyButton";
import classes from "./MarkdownContent.module.css";
import type { MermaidDiagramViewProps } from "../containers/useMermaidDiagramController";

interface MermaidDiagramProps {
  source: string;
}

export function MermaidDiagram(props: MermaidDiagramProps): React.ReactElement {
  return <MermaidDiagramView {...useMermaidDiagramController(props)} />;
}

export function MermaidDiagramView({
  source,
  t,
  state,
}: MermaidDiagramViewProps): React.ReactElement {
  return (
    <Box className={classes.mermaidDiagram}>
      <Box className={classes.mermaidCopyButton}>
        <ChatCopyButton
          value={source}
          copyLabel={t("copy")}
          copiedLabel={t("copied")}
          position="left"
          size="xs"
          iconSize={12}
        />
      </Box>
      {state.type === "RENDERED" ? (
        <Box
          className={classes.mermaidSvg}
          dangerouslySetInnerHTML={{ __html: state.svg }}
        />
      ) : null}
      {state.type === "ERROR" ? (
        <Box className={classes.mermaidFallback}>
          <Text size="xs" c="dimmed" mb="xs">
            {state.message || t("mermaidRenderError")}
          </Text>
          <Box component="pre" className={classes.mermaidFallbackCode}>
            <code>{source}</code>
          </Box>
        </Box>
      ) : null}
      {state.type === "IDLE" ? (
        <Text size="xs" c="dimmed">
          {t("mermaidRendering")}
        </Text>
      ) : null}
    </Box>
  );
}
