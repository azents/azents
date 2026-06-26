# WorkspaceListResponse

Workspace list response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[WorkspaceResponse]**](WorkspaceResponse.md) | Workspace list | 

## Example

```python
from azentspublicclient.models.workspace_list_response import WorkspaceListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceListResponse from a JSON string
workspace_list_response_instance = WorkspaceListResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceListResponse.to_json())

# convert the object into a dict
workspace_list_response_dict = workspace_list_response_instance.to_dict()
# create an instance of WorkspaceListResponse from a dict
workspace_list_response_from_dict = WorkspaceListResponse.from_dict(workspace_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


