"use client";

import { Box, Text, useComputedColorScheme } from "@mantine/core";
import { useTranslations } from "next-intl";
import * as React from "react";
import { ChatCopyButton } from "./ChatCopyButton";
import classes from "./MarkdownContent.module.css";
import type { MermaidConfig } from "mermaid";

interface MermaidDiagramProps {
  source: string;
}

type MermaidDiagramState =
  | { type: "ERROR"; message: string }
  | { type: "IDLE" }
  | { type: "RENDERED"; svg: string };

let nextMermaidDiagramId = 0;

const MERMAID_SECURE_CONFIG_KEYS = [
  "secure",
  "securityLevel",
  "startOnLoad",
  "maxTextSize",
  "maxEdges",
  "theme",
  "themeCSS",
  "themeVariables",
] as const;

function createMermaidDiagramId(): string {
  nextMermaidDiagramId += 1;
  return `azents-mermaid-${nextMermaidDiagramId}`;
}

function getMermaidErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }
  return "";
}

function createMermaidConfig(colorScheme: "dark" | "light"): MermaidConfig {
  return {
    flowchart: {
      useMaxWidth: true,
    },
    maxEdges: 500,
    maxTextSize: 50_000,
    securityLevel: "strict",
    secure: [...MERMAID_SECURE_CONFIG_KEYS],
    sequence: {
      useMaxWidth: true,
    },
    startOnLoad: false,
    suppressErrorRendering: true,
    theme: colorScheme === "dark" ? "dark" : "default",
  };
}

export function MermaidDiagram({
  source,
}: MermaidDiagramProps): React.ReactElement {
  const t = useTranslations("chat");
  const computedColorScheme = useComputedColorScheme("light");
  const colorScheme = computedColorScheme === "dark" ? "dark" : "light";
  const diagramId = React.useMemo(createMermaidDiagramId, []);
  const [state, setState] = React.useState<MermaidDiagramState>({
    type: "IDLE",
  });

  React.useEffect(() => {
    let isCurrent = true;

    async function renderDiagram(): Promise<void> {
      try {
        setState({ type: "IDLE" });
        const mermaidModule = await import("mermaid");
        const mermaid = mermaidModule.default;
        mermaid.initialize(createMermaidConfig(colorScheme));
        const result = await mermaid.render(diagramId, source);
        if (isCurrent) {
          setState({ type: "RENDERED", svg: result.svg });
        }
      } catch (error) {
        if (isCurrent) {
          setState({ type: "ERROR", message: getMermaidErrorMessage(error) });
        }
      }
    }

    void renderDiagram();

    return () => {
      isCurrent = false;
    };
  }, [colorScheme, diagramId, source]);

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
