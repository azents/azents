# WorkspaceRuntimeProfileReplaceRequest

Complete optimistic replacement of one Workspace Runtime Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**infrastructure_profile_id** | **str** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**lifecycle** | [**RuntimeProfileLifecycle**](RuntimeProfileLifecycle.md) |  | 
**policy** | [**WorkspaceRuntimeProfilePolicy**](WorkspaceRuntimeProfilePolicy.md) |  | 
**terminal_enabled** | **bool** |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_profile_replace_request import WorkspaceRuntimeProfileReplaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfileReplaceRequest from a JSON string
workspace_runtime_profile_replace_request_instance = WorkspaceRuntimeProfileReplaceRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfileReplaceRequest.to_json())

# convert the object into a dict
workspace_runtime_profile_replace_request_dict = workspace_runtime_profile_replace_request_instance.to_dict()
# create an instance of WorkspaceRuntimeProfileReplaceRequest from a dict
workspace_runtime_profile_replace_request_from_dict = WorkspaceRuntimeProfileReplaceRequest.from_dict(workspace_runtime_profile_replace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


