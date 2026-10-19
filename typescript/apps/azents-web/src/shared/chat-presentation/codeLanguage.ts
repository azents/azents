import { Prism } from "react-syntax-highlighter";

export function normalizeCodeLanguage(language: string): string {
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

export function supportedCodeLanguage(language: string): string | null {
  const normalizedLanguage = normalizeCodeLanguage(language);
  return Prism.supportedLanguages.includes(normalizedLanguage)
    ? normalizedLanguage
    : null;
}
