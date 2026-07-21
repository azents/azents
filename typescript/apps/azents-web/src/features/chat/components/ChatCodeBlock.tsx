"use client";

import { Box, useComputedColorScheme } from "@mantine/core";
import { useTranslations } from "next-intl";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  prism,
  vscDarkPlus,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import { supportedCodeLanguage } from "../codeLanguage";
import { ChatCopyButton } from "./ChatCopyButton";
import classes from "./MarkdownContent.module.css";
import type { ReactElement } from "react";

interface ChatCodeBlockProps {
  code: string;
  language: string | null;
}

type CodeColorScheme = "dark" | "light";

const CODE_BLOCK_THEMES = {
  dark: vscDarkPlus,
  light: prism,
} as const;

export function ChatCodeBlock({
  code,
  language,
}: ChatCodeBlockProps): ReactElement {
  const t = useTranslations("chat");
  const computedColorScheme = useComputedColorScheme("light");
  const codeColorScheme: CodeColorScheme =
    computedColorScheme === "dark" ? "dark" : "light";
  const codeTheme = CODE_BLOCK_THEMES[codeColorScheme];
  const highlightedLanguage =
    language === null ? null : supportedCodeLanguage(language);

  return (
    <Box className={classes.codeBlockFrame}>
      {highlightedLanguage !== null ? (
        <SyntaxHighlighter
          PreTag="pre"
          CodeTag="code"
          className={classes.codeBlockScroller}
          language={highlightedLanguage}
          style={codeTheme}
          useInlineStyles
          customStyle={{
            background: "transparent",
            color: "inherit",
            margin: 0,
            padding: "0.6em 0.8em",
          }}
          codeTagProps={{
            className: classes.highlightedCode,
            style: {
              background: "transparent",
              color: "inherit",
            },
          }}
        >
          {code}
        </SyntaxHighlighter>
      ) : (
        <Box component="pre" className={classes.codeBlockScroller}>
          <code className={classes.highlightedCode}>{code}</code>
        </Box>
      )}
      <Box className={classes.codeBlockCopyButton}>
        <ChatCopyButton
          value={code}
          copyLabel={t("copy")}
          copiedLabel={t("copied")}
          position="left"
          size="xs"
          iconSize={12}
        />
      </Box>
    </Box>
  );
}
