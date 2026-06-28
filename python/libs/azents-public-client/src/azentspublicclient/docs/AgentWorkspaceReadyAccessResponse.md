# AgentWorkspaceReadyAccessResponse

Agent Workspace ready access response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Response type |
**manifest** | [**AgentWorkspaceManifestResponse**](AgentWorkspaceManifestResponse.md) | Agent Workspace manifest |

## Example

```python
from azentspublicclient.models.agent_workspace_ready_access_response import AgentWorkspaceReadyAccessResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceReadyAccessResponse from a JSON string
agent_workspace_ready_access_response_instance = AgentWorkspaceReadyAccessResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceReadyAccessResponse.to_json())

# convert the object into a dict
agent_workspace_ready_access_response_dict = agent_workspace_ready_access_response_instance.to_dict()
# create an instance of AgentWorkspaceReadyAccessResponse from a dict
agent_workspace_ready_access_response_from_dict = AgentWorkspaceReadyAccessResponse.from_dict(agent_workspace_ready_access_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


