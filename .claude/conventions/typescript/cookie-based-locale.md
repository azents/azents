---
title: "azents-web uses cookie-based next-intl locale management — no `[locale]` URL segments. Detection order is cookie → header → default. Don't add URL-based locale routing here."
---

# Cookie-Based Locale Routing

azents-web is intentionally locale-less in the URL. Translations switch via the `NEXT_LOCALE` cookie plus page reload.

- ALWAYS keep routes locale-less, e.g. `/login`, `/w/{handle}`.
- NEVER add App Router `[locale]` segments for azents-web.
- Preserve the server detection order: cookie → accepted language header → default locale.
