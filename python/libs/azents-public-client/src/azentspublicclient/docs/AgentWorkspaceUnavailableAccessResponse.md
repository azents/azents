# AgentWorkspaceUnavailableAccessResponse

Workspace unavailable response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Response type |
**reason** | **str** | Unavailable reason |

## Example

```python
from azentspublicclient.models.agent_workspace_unavailable_access_response import AgentWorkspaceUnavailableAccessResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceUnavailableAccessResponse from a JSON string
agent_workspace_unavailable_access_response_instance = AgentWorkspaceUnavailableAccessResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceUnavailableAccessResponse.to_json())

# convert the object into a dict
agent_workspace_unavailable_access_response_dict = agent_workspace_unavailable_access_response_instance.to_dict()
# create an instance of AgentWorkspaceUnavailableAccessResponse from a dict
agent_workspace_unavailable_access_response_from_dict = AgentWorkspaceUnavailableAccessResponse.from_dict(agent_workspace_unavailable_access_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
