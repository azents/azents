# WorkspaceRuntimeProfileCreateRequest

Create one complete Workspace Runtime Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**infrastructure_profile_id** | **str** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**lifecycle** | [**RuntimeProfileLifecycle**](RuntimeProfileLifecycle.md) |  | [optional] 
**policy** | [**WorkspaceRuntimeProfilePolicy**](WorkspaceRuntimeProfilePolicy.md) |  | 
**terminal_enabled** | **bool** |  | [optional] [default to True]

## Example

```python
from azentspublicclient.models.workspace_runtime_profile_create_request import WorkspaceRuntimeProfileCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfileCreateRequest from a JSON string
workspace_runtime_profile_create_request_instance = WorkspaceRuntimeProfileCreateRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfileCreateRequest.to_json())

# convert the object into a dict
workspace_runtime_profile_create_request_dict = workspace_runtime_profile_create_request_instance.to_dict()
# create an instance of WorkspaceRuntimeProfileCreateRequest from a dict
workspace_runtime_profile_create_request_from_dict = WorkspaceRuntimeProfileCreateRequest.from_dict(workspace_runtime_profile_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


