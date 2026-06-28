# AgentWorkspaceRuntimeResponse

Server-computed Agent Runtime status response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Provider runtime status |
**runtime_id** | **str** |  |
**workspace_path** | **str** |  | [optional]
**detail** | **str** |  | [optional]

## Example

```python
from azentspublicclient.models.agent_workspace_runtime_response import AgentWorkspaceRuntimeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceRuntimeResponse from a JSON string
agent_workspace_runtime_response_instance = AgentWorkspaceRuntimeResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceRuntimeResponse.to_json())

# convert the object into a dict
agent_workspace_runtime_response_dict = agent_workspace_runtime_response_instance.to_dict()
# create an instance of AgentWorkspaceRuntimeResponse from a dict
agent_workspace_runtime_response_from_dict = AgentWorkspaceRuntimeResponse.from_dict(agent_workspace_runtime_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


