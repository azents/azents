---
title: Use supported external-service SDK public APIs instead of hand-written provider calls; exceptions require requester approval.
---

# Prefer supported external service SDKs

SDK ownership avoids duplicating provider routes, authentication, protocol behavior, retries, and compatibility updates in Azents.

- ALWAYS use an existing official or established SDK's public API when it supports the required external-service operation.
- NEVER bypass a supported SDK operation with hand-written HTTP, WebSocket, or protocol code merely because a direct call appears smaller or easier to test.
- NEVER depend on private or internal SDK APIs as a substitute for a missing public API.
- A direct provider call is allowed only when the SDK lacks the required public capability, the gap and operational consequences are documented, and the requester explicitly approves the exception.
- When replacing a direct call with SDK support, remove the obsolete transport code and update tests to exercise the SDK-owned boundary.

## Bad

```python
await http_client.patch(
    "https://provider.example/api/application",
    json={"callback_url": callback_url},
)
```

## Good

```python
application = await provider_client.application_info()
await application.edit(callback_url=callback_url)
```
