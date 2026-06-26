# WorkspaceUserListResponse

WorkspaceUser list response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[WorkspaceUserResponse]**](WorkspaceUserResponse.md) | WorkspaceUser list | 

## Example

```python
from azentspublicclient.models.workspace_user_list_response import WorkspaceUserListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceUserListResponse from a JSON string
workspace_user_list_response_instance = WorkspaceUserListResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceUserListResponse.to_json())

# convert the object into a dict
workspace_user_list_response_dict = workspace_user_list_response_instance.to_dict()
# create an instance of WorkspaceUserListResponse from a dict
workspace_user_list_response_from_dict = WorkspaceUserListResponse.from_dict(workspace_user_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


