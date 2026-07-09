"use client";

/** Render chat Markdown with compact typography, GFM, code highlighting, and Mermaid diagrams. */

import { Box, useComputedColorScheme } from "@mantine/core";
import { useTranslations } from "next-intl";
import * as React from "react";
import Markdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  prism,
  vscDarkPlus,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { ChatCopyButton } from "./ChatCopyButton";
import classes from "./MarkdownContent.module.css";
import { MermaidDiagram } from "./MermaidDiagram";
import type { Components, ExtraProps } from "react-markdown";

interface MarkdownContentProps {
  children: string;
}

type MarkdownAnchorProps = React.ComponentPropsWithoutRef<"a"> & ExtraProps;
type MarkdownPreProps = React.ComponentPropsWithoutRef<"pre"> & ExtraProps;
type CodeColorScheme = "dark" | "light";

const CODE_BLOCK_THEMES = {
  dark: vscDarkPlus,
  light: prism,
} as const;

function collectTextContent(node: React.ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(collectTextContent).join("");
  }
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) {
    return collectTextContent(node.props.children);
  }
  return "";
}

function normalizeCodeLanguage(language: string): string {
  switch (language.toLowerCase()) {
    case "c++":
    case "cpp":
      return "cpp";
    case "c#":
    case "cs":
    case "csharp":
      return "csharp";
    case "diff":
    case "git-diff":
    case "gitdiff":
    case "patch":
    case "udiff":
      return "diff";
    case "dockerfile":
    case "docker":
      return "docker";
    case "dotenv":
    case "env":
      return "dotenv";
    case "golang":
    case "go":
      return "go";
    case "html":
    case "html5":
      return "markup";
    case "js":
    case "javascript":
      return "javascript";
    case "md":
    case "mdx":
    case "markdown":
      return "markdown";
    case "py":
    case "python":
      return "python";
    case "rb":
    case "ruby":
      return "ruby";
    case "rs":
    case "rust":
      return "rust";
    case "sh":
    case "shell":
    case "zsh":
      return "bash";
    case "tf":
    case "terraform":
      return "hcl";
    case "ts":
    case "typescript":
      return "typescript";
    case "yml":
    case "yaml":
      return "yaml";
    default:
      return language.toLowerCase();
  }
}

function getCodeLanguage(node: React.ReactNode): string | null {
  if (!React.isValidElement<{ className?: string }>(node)) {
    return null;
  }

  const className = node.props.className ?? "";
  const match = /language-(\S+)/u.exec(className);
  if (!match) {
    return null;
  }

  const language = match[1];
  if (!language) {
    return null;
  }

  return normalizeCodeLanguage(language);
}

function MarkdownLink({
  children,
  node,
  ...props
}: MarkdownAnchorProps): React.ReactElement {
  void node;

  return (
    <a rel="noopener noreferrer" target="_blank" {...props}>
      {children}
    </a>
  );
}

function CodeBlock({
  children,
  node,
  ...props
}: MarkdownPreProps): React.ReactElement {
  void node;

  const t = useTranslations("chat");
  const computedColorScheme = useComputedColorScheme("light");
  const codeColorScheme: CodeColorScheme =
    computedColorScheme === "dark" ? "dark" : "light";
  const codeTheme = CODE_BLOCK_THEMES[codeColorScheme];
  const codeText = collectTextContent(children).replace(/\n$/, "");
  const language = getCodeLanguage(children);

  if (language === "mermaid") {
    return <MermaidDiagram source={codeText} />;
  }

  return (
    <Box className={classes.codeBlock} component="pre" {...props}>
      <Box className={classes.codeBlockCopyButton}>
        <ChatCopyButton
          value={codeText}
          copyLabel={t("copy")}
          copiedLabel={t("copied")}
          position="left"
          size="xs"
          iconSize={12}
        />
      </Box>
      {language ? (
        <SyntaxHighlighter
          PreTag="div"
          CodeTag="code"
          language={language}
          style={codeTheme}
          useInlineStyles
          customStyle={{
            background: "var(--azents-chat-code-background)",
            color: "var(--azents-chat-code-foreground)",
            margin: 0,
            padding: 0,
          }}
          codeTagProps={{
            className: classes.highlightedCode,
            style: {
              background: "var(--azents-chat-code-background)",
              color: "var(--azents-chat-code-foreground)",
            },
          }}
        >
          {codeText}
        </SyntaxHighlighter>
      ) : (
        children
      )}
    </Box>
  );
}

const markdownComponents: Components = {
  a: MarkdownLink,
  pre: CodeBlock,
};

export function MarkdownContent({
  children,
}: MarkdownContentProps): React.ReactElement {
  return (
    <div className={classes.markdown}>
      <Markdown
        components={markdownComponents}
        remarkPlugins={[remarkGfm, remarkBreaks]}
      >
        {children}
      </Markdown>
    </div>
  );
}
