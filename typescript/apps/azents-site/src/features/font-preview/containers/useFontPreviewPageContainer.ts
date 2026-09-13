"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { FontPreviewCopy, FontPreviewOption } from "../types";

const fontOptions = [
  {
    name: "Inter Variable",
    stack: "var(--font-azents-sans)",
    noteKey: "current",
  },
  {
    name: "System UI",
    stack:
      "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', sans-serif",
    noteKey: "native",
  },
  {
    name: "Avenir Next",
    stack:
      "'Avenir Next', Avenir, -apple-system, BlinkMacSystemFont, sans-serif",
    noteKey: "warmer",
  },
  {
    name: "Helvetica Neue",
    stack: "'Helvetica Neue', Helvetica, Arial, -apple-system, sans-serif",
    noteKey: "neutral",
  },
  {
    name: "Inter stack",
    stack: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    noteKey: "fallback",
  },
  {
    name: "IBM Plex Sans stack",
    stack:
      "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    noteKey: "fallback",
  },
  {
    name: "Georgia",
    stack: "Georgia, 'Times New Roman', serif",
    noteKey: "editorial",
  },
] as const;

export interface FontPreviewPageContainerOutput {
  options: readonly FontPreviewOption[];
  copy: FontPreviewCopy;
}

export function useFontPreviewPageContainer(): FontPreviewPageContainerOutput {
  const t = useTranslations("fontPreview");
  const [computedFonts, setComputedFonts] = useState<Record<string, string>>(
    {},
  );

  useEffect(() => {
    const next: Record<string, string> = {};
    for (const option of fontOptions) {
      const element = document.querySelector<HTMLElement>(
        `[data-font-preview="${option.name}"]`,
      );
      if (element) {
        next[option.name] = getComputedStyle(element).fontFamily;
      }
    }
    setComputedFonts(next);
  }, []);

  return {
    options: fontOptions.map((option) => ({
      name: option.name,
      stack: option.stack,
      note: t(`notes.${option.noteKey}`),
      computedFont: computedFonts[option.name] ?? t("checking"),
    })),
    copy: {
      sampleLabel: t("sampleLabel"),
      eyebrow: t("eyebrow"),
      headline: t("headline"),
      subheadline: t("subheadline"),
      supporting: t("supporting"),
      rendered: t("rendered"),
      pageEyebrow: t("pageEyebrow"),
      pageTitle: t("pageTitle"),
      pageBody: t("pageBody"),
    },
  };
}
