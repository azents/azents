# AgentWorkspaceBulkDeleteRequest

Agent Workspace bulk delete request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**paths** | **List[str]** | File or directory paths to delete | 
**recursive** | **bool** | Delete directories recursively | [optional] [default to False]

## Example

```python
from azentspublicclient.models.agent_workspace_bulk_delete_request import AgentWorkspaceBulkDeleteRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentWorkspaceBulkDeleteRequest from a JSON string
agent_workspace_bulk_delete_request_instance = AgentWorkspaceBulkDeleteRequest.from_json(json)
# print the JSON string representation of the object
print(AgentWorkspaceBulkDeleteRequest.to_json())

# convert the object into a dict
agent_workspace_bulk_delete_request_dict = agent_workspace_bulk_delete_request_instance.to_dict()
# create an instance of AgentWorkspaceBulkDeleteRequest from a dict
agent_workspace_bulk_delete_request_from_dict = AgentWorkspaceBulkDeleteRequest.from_dict(agent_workspace_bulk_delete_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


