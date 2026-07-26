# AgentSessionPinUpdateRequest

AgentSession automatic-archive protection update request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**pinned** | **bool** | Whether automatic archive is disabled for this active non-primary root Session | 

## Example

```python
from azentspublicclient.models.agent_session_pin_update_request import AgentSessionPinUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionPinUpdateRequest from a JSON string
agent_session_pin_update_request_instance = AgentSessionPinUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(AgentSessionPinUpdateRequest.to_json())

# convert the object into a dict
agent_session_pin_update_request_dict = agent_session_pin_update_request_instance.to_dict()
# create an instance of AgentSessionPinUpdateRequest from a dict
agent_session_pin_update_request_from_dict = AgentSessionPinUpdateRequest.from_dict(agent_session_pin_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


