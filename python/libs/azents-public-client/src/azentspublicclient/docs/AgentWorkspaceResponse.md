# AgentWorkspaceResponse

Agent Workspace panel bootstrap response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**runtime** | [**AgentWorkspaceRuntimeResponse**](AgentWorkspaceRuntimeResponse.md) | Provider runtime status |
**workspace** | [**Workspace**](Workspace.md) |  |
**actions** | [**AgentWorkspaceActionsResponse**](AgentWorkspaceActionsResponse.md) | Runtime lifecycle actions |

## Example

```python
from azentspublicclient.models.agent_workspace_response import AgentWorkspaceResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceResponse from a JSON string
agent_workspace_response_instance = AgentWorkspaceResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceResponse.to_json())

# convert the object into a dict
agent_workspace_response_dict = agent_workspace_response_instance.to_dict()
# create an instance of AgentWorkspaceResponse from a dict
agent_workspace_response_from_dict = AgentWorkspaceResponse.from_dict(agent_workspace_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
