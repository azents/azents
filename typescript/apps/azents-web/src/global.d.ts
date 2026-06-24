/**
 * next-intl type safety settings.
 *
 * Uses en-US.json as the reference type to validate useTranslations namespace
 * and key at compile time.
 */
import type en from "../messages/en-US.json";

type Messages = typeof en;

declare module "next-intl" {
  interface AppConfig {
    Messages: Messages;
  }
}
