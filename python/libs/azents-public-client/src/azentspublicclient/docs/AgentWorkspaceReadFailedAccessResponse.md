# AgentWorkspaceReadFailedAccessResponse

Workspace read/list failure response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Response type |
**detail** | **str** | Status description |

## Example

```python
from azentspublicclient.models.agent_workspace_read_failed_access_response import AgentWorkspaceReadFailedAccessResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceReadFailedAccessResponse from a JSON string
agent_workspace_read_failed_access_response_instance = AgentWorkspaceReadFailedAccessResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceReadFailedAccessResponse.to_json())

# convert the object into a dict
agent_workspace_read_failed_access_response_dict = agent_workspace_read_failed_access_response_instance.to_dict()
# create an instance of AgentWorkspaceReadFailedAccessResponse from a dict
agent_workspace_read_failed_access_response_from_dict = AgentWorkspaceReadFailedAccessResponse.from_dict(agent_workspace_read_failed_access_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
