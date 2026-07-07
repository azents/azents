import type en from "../messages/en-US.json";

type Messages = typeof en;

declare module "next-intl" {
  interface AppConfig {
    Messages: Messages;
  }
}

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (command: string, ...args: unknown[]) => void;
  }
}
