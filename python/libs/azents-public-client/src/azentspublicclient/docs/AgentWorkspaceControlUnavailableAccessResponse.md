# AgentWorkspaceControlUnavailableAccessResponse

Runner route/stream unavailable response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Response type |
**detail** | **str** | Status description |
**retry_after_ms** | **int** | Recommended retry delay |

## Example

```python
from azentspublicclient.models.agent_workspace_control_unavailable_access_response import AgentWorkspaceControlUnavailableAccessResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceControlUnavailableAccessResponse from a JSON string
agent_workspace_control_unavailable_access_response_instance = AgentWorkspaceControlUnavailableAccessResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceControlUnavailableAccessResponse.to_json())

# convert the object into a dict
agent_workspace_control_unavailable_access_response_dict = agent_workspace_control_unavailable_access_response_instance.to_dict()
# create an instance of AgentWorkspaceControlUnavailableAccessResponse from a dict
agent_workspace_control_unavailable_access_response_from_dict = AgentWorkspaceControlUnavailableAccessResponse.from_dict(agent_workspace_control_unavailable_access_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
