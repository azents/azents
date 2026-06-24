/**
 * Sentry client side settings
 *
 * error collectiont enable. performance monitoring, session replay t disable.
 */
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  enabled: !!process.env.NEXT_PUBLIC_SENTRY_DSN,

  // error collectiont — performance monitoring disable
  tracesSampleRate: 0,

  // debug log disable
  debug: false,
});
