---
title: "Slack-flow QA results posted as PR comments must include a clickable Slack conversation link (`https://{workspace}.slack.com/archives/{channel_id}/p{ts_no_dot}`) — the result JSON alone does not prove the message exists in Slack."
---

# QA Report: Include the Slack Conversation Link

A passing JSON result tells you the runner thinks it succeeded; only a real Slack link proves the message landed in the workspace where reviewers can verify it.

- Build the link from `channel_id` + `parent_ts` in the runner's result JSON
- Format: `https://{workspace}.slack.com/archives/{channel_id}/p{ts_without_dot}`
  - `ts` `1775961394.123456` → strip `.` → `p1775961394123456`
- Use `_helpers.slack.slack_message_link()` rather than building by hand

## Workflow

```python
from testenv.azents._helpers.slack import slack_message_link

link = slack_message_link(
    workspace="azentssandbox",
    channel_id=result["channel_id"],
    ts=result["parent_ts"],
)
# include `link` in the PR comment markdown
```
