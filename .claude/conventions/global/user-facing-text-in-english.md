---
title: "All log lines, error messages, API response messages, and WebSocket text returned to users or operators must be in English — this is a global service whose users do not read Korean."
---

# User-Facing Text in English

English is required for source code and for anything that crosses the runtime boundary. End users and operators may not read Korean.

- ALWAYS write log messages (`logger.info/warning/error/exception`), API error responses, and WebSocket payload text in English
- Comments and docstrings are also English — see `comments-and-docstrings-in-english.md`

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
