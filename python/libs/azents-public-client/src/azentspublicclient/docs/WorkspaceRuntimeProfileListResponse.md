# WorkspaceRuntimeProfileListResponse

Workspace-owned Runtime Profile list.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[WorkspaceRuntimeProfileResponse]**](WorkspaceRuntimeProfileResponse.md) |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_profile_list_response import WorkspaceRuntimeProfileListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfileListResponse from a JSON string
workspace_runtime_profile_list_response_instance = WorkspaceRuntimeProfileListResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfileListResponse.to_json())

# convert the object into a dict
workspace_runtime_profile_list_response_dict = workspace_runtime_profile_list_response_instance.to_dict()
# create an instance of WorkspaceRuntimeProfileListResponse from a dict
workspace_runtime_profile_list_response_from_dict = WorkspaceRuntimeProfileListResponse.from_dict(workspace_runtime_profile_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


