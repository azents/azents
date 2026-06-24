---
title: "All log lines, error messages, API response messages, and WebSocket text returned to users or operators must be in English — this is a global service whose users do not read Korean."
---

# User-Facing Text in English

Korean is for the source code; English is for anything that crosses the runtime boundary. End users and operators may not read Korean.

- ALWAYS write log messages (`logger.info/warning/error/exception`), API error responses, and WebSocket payload text in English
- Korean stays inside comments and docstrings only — see `comments-and-docstrings-in-korean.md`

## Bad

```python
logger.info("워크플로우 시작", extra={"workflow_id": wf_id})
raise HTTPException(status_code=400, detail="요청이 잘못되었습니다")
```

## Good

```python
logger.info("Starting workflow", extra={"workflow_id": wf_id})
raise HTTPException(status_code=400, detail="Invalid request")
```
