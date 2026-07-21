import langMap from "lang-map";
import { supportedCodeLanguage } from "./codeLanguage.ts";

function languageLookupKey(path: string): string | null {
  const fileName = path.replaceAll("\\", "/").split("/").at(-1)?.trim();
  if (!fileName) {
    return null;
  }
  const dotIndex = fileName.lastIndexOf(".");
  if (dotIndex > 0 && dotIndex < fileName.length - 1) {
    return fileName.slice(dotIndex + 1).toLowerCase();
  }
  return fileName.replace(/^\./u, "").toLowerCase();
}

export function fileCodeLanguage(path: string): string | null {
  const lookupKey = languageLookupKey(path);
  if (lookupKey === null || !Object.hasOwn(langMap().languages, lookupKey)) {
    return null;
  }
  return (
    langMap.languages(lookupKey).map(supportedCodeLanguage).find(Boolean) ??
    null
  );
}
