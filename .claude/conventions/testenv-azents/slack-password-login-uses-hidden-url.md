---
title: "Slack password automation must POST to `https://{workspace}.slack.com/sign_in_with_password` (hidden but valid) — the visible `/signin` page only exposes email-code flow since the 2024 UI rework. Use `page.press(\"input[name=password]\", \"Enter\")` (not click) and verify success via `d` cookie starting with `xoxd-`, not URL redirect."
---

# Slack Password Login: Use the Hidden URL

The default Slack `/signin` page since the 2024 UI rework only shows "Sign In With Email" → email-code flow. Password-based automation must use the legacy `/sign_in_with_password` endpoint, which still renders the email + password form.

- ALWAYS POST/navigate to `https://{workspace}.slack.com/sign_in_with_password`
- Submit with `page.press("input[name='password']", "Enter")` — `page.click('button[type="submit"]')` produces intermittent `net::ERR_ABORTED`
- Success check: read `d` cookie and verify it starts with `xoxd-`. Do NOT wait for a redirect to `app.slack.com/client` — that page can fail to load in headless even when the session is valid.

## Bad

```python
await page.goto(f"https://{ws}.slack.com/signin")  # email-code flow only — no password field
await page.click("button[type='submit']")          # produces ERR_ABORTED randomly
await page.wait_for_url(f"https://app.slack.com/client/{team_id}")  # fails in headless
```

## Good

```python
await page.goto(f"https://{ws}.slack.com/sign_in_with_password")
await page.fill("input[name='email']", email)
await page.fill("input[name='password']", password)
await page.press("input[name='password']", "Enter")

cookies = {c["name"]: c["value"] for c in await context.cookies()}
assert cookies["d"].startswith("xoxd-"), "login failed"
```

Reference: `setup_handlers/slack_account_session.py`.
