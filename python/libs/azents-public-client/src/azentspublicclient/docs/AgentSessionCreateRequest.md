# AgentSessionCreateRequest

REST non-primary AgentSession create request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_mode** | [**WorkspaceMode**](WorkspaceMode.md) |  | [optional] 
**project_paths** | **List[str]** |  | [optional] 

## Example

```python
from azentspublicclient.models.agent_session_create_request import AgentSessionCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionCreateRequest from a JSON string
agent_session_create_request_instance = AgentSessionCreateRequest.from_json(json)
# print the JSON string representation of the object
print(AgentSessionCreateRequest.to_json())

# convert the object into a dict
agent_session_create_request_dict = agent_session_create_request_instance.to_dict()
# create an instance of AgentSessionCreateRequest from a dict
agent_session_create_request_from_dict = AgentSessionCreateRequest.from_dict(agent_session_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


