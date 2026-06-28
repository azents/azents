# AgentWorkspaceBulkMoveRequest

Agent Workspace bulk move request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**source_paths** | **List[str]** | Source paths |
**destination_directory** | **str** | Destination directory |
**overwrite** | **bool** | Overwrite existing destinations | [optional] [default to False]

## Example

```python
from azentspublicclient.models.agent_workspace_bulk_move_request import AgentWorkspaceBulkMoveRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceBulkMoveRequest from a JSON string
agent_workspace_bulk_move_request_instance = AgentWorkspaceBulkMoveRequest.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceBulkMoveRequest.to_json())

# convert the object into a dict
agent_workspace_bulk_move_request_dict = agent_workspace_bulk_move_request_instance.to_dict()
# create an instance of AgentWorkspaceBulkMoveRequest from a dict
agent_workspace_bulk_move_request_from_dict = AgentWorkspaceBulkMoveRequest.from_dict(agent_workspace_bulk_move_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


