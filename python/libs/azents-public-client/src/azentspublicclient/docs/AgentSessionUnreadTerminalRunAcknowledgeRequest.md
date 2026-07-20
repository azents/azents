# AgentSessionUnreadTerminalRunAcknowledgeRequest

Observed terminal Run boundary acknowledged as reviewed.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**through_run_id** | **str** | Observed terminal AgentRun ID | 

## Example

```python
from azentspublicclient.models.agent_session_unread_terminal_run_acknowledge_request import AgentSessionUnreadTerminalRunAcknowledgeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionUnreadTerminalRunAcknowledgeRequest from a JSON string
agent_session_unread_terminal_run_acknowledge_request_instance = AgentSessionUnreadTerminalRunAcknowledgeRequest.from_json(json)
# print the JSON string representation of the object
print(AgentSessionUnreadTerminalRunAcknowledgeRequest.to_json())

# convert the object into a dict
agent_session_unread_terminal_run_acknowledge_request_dict = agent_session_unread_terminal_run_acknowledge_request_instance.to_dict()
# create an instance of AgentSessionUnreadTerminalRunAcknowledgeRequest from a dict
agent_session_unread_terminal_run_acknowledge_request_from_dict = AgentSessionUnreadTerminalRunAcknowledgeRequest.from_dict(agent_session_unread_terminal_run_acknowledge_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


