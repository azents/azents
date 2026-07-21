declare module "lang-map" {
  interface LanguageMapData {
    extensions: Record<string, readonly string[]>;
    languages: Record<string, readonly string[]>;
  }

  interface LanguageMap {
    (): LanguageMapData;
    extensions(language: string): string[];
    languages(extension: string): string[];
  }

  const langMap: LanguageMap;
  export default langMap;
}
