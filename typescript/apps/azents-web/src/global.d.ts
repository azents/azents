/**
 * next-intl type safety settings.
 *
 * Uses the composed en-US messages as the reference type to validate useTranslations namespace
 * and key at compile time.
 */
import type en from "./i18n/en-US-messages";

type Messages = typeof en;

declare module "next-intl" {
  interface AppConfig {
    Messages: Messages;
  }
}
