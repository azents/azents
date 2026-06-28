# AgentWorkspaceConnectingAccessResponse

Workspace connecting response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Response type |

## Example

```python
from azentspublicclient.models.agent_workspace_connecting_access_response import AgentWorkspaceConnectingAccessResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceConnectingAccessResponse from a JSON string
agent_workspace_connecting_access_response_instance = AgentWorkspaceConnectingAccessResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceConnectingAccessResponse.to_json())

# convert the object into a dict
agent_workspace_connecting_access_response_dict = agent_workspace_connecting_access_response_instance.to_dict()
# create an instance of AgentWorkspaceConnectingAccessResponse from a dict
agent_workspace_connecting_access_response_from_dict = AgentWorkspaceConnectingAccessResponse.from_dict(agent_workspace_connecting_access_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


