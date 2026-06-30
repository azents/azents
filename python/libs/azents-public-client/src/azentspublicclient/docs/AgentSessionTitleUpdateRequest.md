# AgentSessionTitleUpdateRequest

AgentSession title update request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**title** | **str** |  | 

## Example

```python
from azentspublicclient.models.agent_session_title_update_request import AgentSessionTitleUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionTitleUpdateRequest from a JSON string
agent_session_title_update_request_instance = AgentSessionTitleUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(AgentSessionTitleUpdateRequest.to_json())

# convert the object into a dict
agent_session_title_update_request_dict = agent_session_title_update_request_instance.to_dict()
# create an instance of AgentSessionTitleUpdateRequest from a dict
agent_session_title_update_request_from_dict = AgentSessionTitleUpdateRequest.from_dict(agent_session_title_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


