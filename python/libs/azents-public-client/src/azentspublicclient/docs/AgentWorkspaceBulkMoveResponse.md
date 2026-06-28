# AgentWorkspaceBulkMoveResponse

Agent Workspace bulk move response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**entries** | [**List[AgentWorkspaceMoveResponse]**](AgentWorkspaceMoveResponse.md) | Moved entries |

## Example

```python
from azentspublicclient.models.agent_workspace_bulk_move_response import AgentWorkspaceBulkMoveResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceBulkMoveResponse from a JSON string
agent_workspace_bulk_move_response_instance = AgentWorkspaceBulkMoveResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceBulkMoveResponse.to_json())

# convert the object into a dict
agent_workspace_bulk_move_response_dict = agent_workspace_bulk_move_response_instance.to_dict()
# create an instance of AgentWorkspaceBulkMoveResponse from a dict
agent_workspace_bulk_move_response_from_dict = AgentWorkspaceBulkMoveResponse.from_dict(agent_workspace_bulk_move_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


