import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import classes from "./AttachmentMarkdownPreview.module.css";
import type { ComponentPropsWithoutRef } from "react";
import type { Components, ExtraProps } from "react-markdown";

interface AttachmentMarkdownPreviewProps {
  text: string;
}

type MarkdownAnchorProps = ComponentPropsWithoutRef<"a"> & ExtraProps;
type MarkdownImageProps = ComponentPropsWithoutRef<"img"> & ExtraProps;

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

function MarkdownImage({
  alt,
  node,
  src,
}: MarkdownImageProps): React.ReactElement {
  void node;
  if (typeof src !== "string" || src.length === 0) {
    return <span>{alt ?? ""}</span>;
  }
  return (
    <a href={src} rel="noopener noreferrer" target="_blank">
      {alt || src}
    </a>
  );
}

const markdownComponents: Components = {
  a: MarkdownLink,
  img: MarkdownImage,
};

export function AttachmentMarkdownPreview({
  text,
}: AttachmentMarkdownPreviewProps): React.ReactElement {
  return (
    <div className={classes.markdown}>
      <ReactMarkdown
        components={markdownComponents}
        remarkPlugins={[remarkGfm]}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
