---
title: "Always create timezone-aware datetimes via `datetime.now(timezone.utc)` — never use `datetime.now()` or `datetime.utcnow()`, which return naïve objects that compare incorrectly across boundaries."
---

# Timezone-Aware Datetimes

A naïve datetime compared against an aware one raises `TypeError`. Worse, two naïve datetimes from different sources may silently encode different timezones and compare as if they were the same.

- ALWAYS use `datetime.now(timezone.utc)` (or `datetime.now(ZoneInfo(...))` for a specific zone)
- AVOID `datetime.now()` and `datetime.utcnow()`

## Bad

```python
from datetime import datetime

created_at = datetime.now()
expires_at = datetime.utcnow() + timedelta(hours=1)
```

## Good

```python
from datetime import datetime, timezone, timedelta

created_at = datetime.now(timezone.utc)
expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
```
