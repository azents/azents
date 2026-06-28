# AgentWorkspaceBulkDeleteResponse

Agent Workspace bulk delete response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**paths** | **List[str]** | Deleted paths |

## Example

```python
from azentspublicclient.models.agent_workspace_bulk_delete_response import AgentWorkspaceBulkDeleteResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceBulkDeleteResponse from a JSON string
agent_workspace_bulk_delete_response_instance = AgentWorkspaceBulkDeleteResponse.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceBulkDeleteResponse.to_json())

# convert the object into a dict
agent_workspace_bulk_delete_response_dict = agent_workspace_bulk_delete_response_instance.to_dict()
# create an instance of AgentWorkspaceBulkDeleteResponse from a dict
agent_workspace_bulk_delete_response_from_dict = AgentWorkspaceBulkDeleteResponse.from_dict(agent_workspace_bulk_delete_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


