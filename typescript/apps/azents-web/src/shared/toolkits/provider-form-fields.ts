import { getString, getStringArray } from "../lib/unknown-value.ts";

/** Editable projections deliberately preserve partial strings and unknown fields. */
export interface BraveFormFields {
  apiKey: string;
  country: string;
  language: string;
  safesearch: string;
  timeout: number;
}
export function projectBraveFormFields(
  config: Record<string, unknown>,
  credentials: Record<string, unknown> | null,
): BraveFormFields {
  return {
    apiKey: typeof credentials?.api_key === "string" ? credentials.api_key : "",
    country: typeof config.country === "string" ? config.country : "US",
    language:
      typeof config.search_lang === "string" ? config.search_lang : "en",
    safesearch:
      typeof config.safesearch === "string" ? config.safesearch : "strict",
    timeout: typeof config.timeout === "number" ? config.timeout : 10,
  };
}
export interface BraveFieldCallbacks {
  onApiKeyChange: (value: string) => void;
  onCountryChange: (value: string) => void;
  onLanguageChange: (value: string) => void;
  onSafesearchChange: (value: string | null) => void;
  onTimeoutChange: (value: string | number) => void;
}
export function braveFieldCallbacks(
  config: Record<string, unknown>,
  onConfigChange: (config: Record<string, unknown>) => void,
  onCredentialsChange: (credentials: Record<string, unknown> | null) => void,
): BraveFieldCallbacks {
  return {
    onApiKeyChange: (value) =>
      onCredentialsChange(value ? { api_key: value } : null),
    onCountryChange: (value) =>
      onConfigChange({ ...config, country: value.toUpperCase() }),
    onLanguageChange: (value) =>
      onConfigChange({ ...config, search_lang: value.toLowerCase() }),
    onSafesearchChange: (value) =>
      onConfigChange({ ...config, safesearch: value ?? "strict" }),
    onTimeoutChange: (value) => onConfigChange({ ...config, timeout: value }),
  };
}
export interface GithubCredentialFields {
  token: string;
  app_id: string;
  private_key: string;
  client_id: string;
  client_secret: string;
}
export interface GithubFormFields {
  auth: string;
  credentials: GithubCredentialFields;
  toolsets: string[];
  injectRuntimeEnvironment: boolean;
}
export function projectGithubFormFields(
  config: Record<string, unknown>,
  credentials: Record<string, unknown> | null,
): GithubFormFields {
  return {
    auth: getString(config.github_auth_type) || "pat",
    credentials: {
      token: getString(credentials?.token),
      app_id: getString(credentials?.app_id),
      private_key: getString(credentials?.private_key),
      client_id: getString(credentials?.client_id),
      client_secret: getString(credentials?.client_secret),
    },
    toolsets: Array.isArray(config.toolsets)
      ? getStringArray(config.toolsets)
      : ["repos", "issues", "pull_requests", "users"],
    injectRuntimeEnvironment: Boolean(config.inject_runtime_environment),
  };
}
export interface GithubFieldCallbacks {
  onAuthChange: (value: string | null) => void;
  onCredentialFieldChange: (
    key: keyof GithubCredentialFields,
    value: string,
  ) => void;
  onToolsetsChange: (values: string[]) => void;
  onInjectRuntimeEnvironmentChange: (value: boolean) => void;
}
export function githubFieldCallbacks(
  config: Record<string, unknown>,
  credentials: Record<string, unknown> | null,
  onConfigChange: (config: Record<string, unknown>) => void,
  onCredentialsChange: (credentials: Record<string, unknown> | null) => void,
): GithubFieldCallbacks {
  return {
    onAuthChange: (value) => {
      const next = value ?? "pat";
      onConfigChange({
        ...config,
        github_auth_type: next,
        auth_type: "bearer",
      });
      onCredentialsChange({ type: next });
    },
    onCredentialFieldChange: (key, value) =>
      onCredentialsChange({ ...credentials, [key]: value }),
    onToolsetsChange: (values) =>
      onConfigChange({ ...config, toolsets: values }),
    onInjectRuntimeEnvironmentChange: (value) =>
      onConfigChange({ ...config, inject_runtime_environment: value }),
  };
}
