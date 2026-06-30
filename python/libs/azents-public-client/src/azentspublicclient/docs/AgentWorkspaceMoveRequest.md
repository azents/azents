# AgentWorkspaceMoveRequest

Agent Workspace move request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**source_path** | **str** | Source path | 
**destination_path** | **str** | Destination path | 
**overwrite** | **bool** | Overwrite existing destination | [optional] [default to False]

## Example

```python
from azentspublicclient.models.agent_workspace_move_request import AgentWorkspaceMoveRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceMoveRequest from a JSON string
agent_workspace_move_request_instance = AgentWorkspaceMoveRequest.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceMoveRequest.to_json())

# convert the object into a dict
agent_workspace_move_request_dict = agent_workspace_move_request_instance.to_dict()
# create an instance of AgentWorkspaceMoveRequest from a dict
agent_workspace_move_request_from_dict = AgentWorkspaceMoveRequest.from_dict(agent_workspace_move_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


