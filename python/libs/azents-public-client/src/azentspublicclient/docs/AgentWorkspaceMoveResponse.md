# AgentWorkspaceMoveResponse

Agent Workspace move response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**source_path** | **str** | Moved source path | 
**destination_path** | **str** | Move destination path | 

## Example

```python
from azentspublicclient.models.agent_workspace_move_response import AgentWorkspaceMoveResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceMoveResponse from a JSON string
agent_workspace_move_response_instance = AgentWorkspaceMoveResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceMoveResponse.to_json())

# convert the object into a dict
agent_workspace_move_response_dict = agent_workspace_move_response_instance.to_dict()
# create an instance of AgentWorkspaceMoveResponse from a dict
agent_workspace_move_response_from_dict = AgentWorkspaceMoveResponse.from_dict(agent_workspace_move_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


