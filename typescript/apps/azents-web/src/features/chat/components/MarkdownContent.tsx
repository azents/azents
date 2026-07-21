"use client";

/** Render chat Markdown with compact typography, GFM, code highlighting, and Mermaid diagrams. */

import * as React from "react";
import Markdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { normalizeCodeLanguage } from "../codeLanguage";
import { ChatCodeBlock } from "./ChatCodeBlock";
import classes from "./MarkdownContent.module.css";
import { MermaidDiagram } from "./MermaidDiagram";
import type { Components, ExtraProps } from "react-markdown";

interface MarkdownContentProps {
  children: string;
}

type MarkdownAnchorProps = React.ComponentPropsWithoutRef<"a"> & ExtraProps;
type MarkdownPreProps = React.ComponentPropsWithoutRef<"pre"> & ExtraProps;
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

  const codeText = collectTextContent(children).replace(/\n$/, "");
  const language = getCodeLanguage(children);

  if (language === "mermaid") {
    return <MermaidDiagram source={codeText} />;
  }

  void props;
  return <ChatCodeBlock code={codeText} language={language} />;
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
