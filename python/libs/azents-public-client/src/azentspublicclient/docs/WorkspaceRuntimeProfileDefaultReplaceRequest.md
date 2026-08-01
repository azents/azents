# WorkspaceRuntimeProfileDefaultReplaceRequest

Optimistically set or clear the Workspace Runtime Profile default.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**runtime_profile_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_profile_default_replace_request import WorkspaceRuntimeProfileDefaultReplaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfileDefaultReplaceRequest from a JSON string
workspace_runtime_profile_default_replace_request_instance = WorkspaceRuntimeProfileDefaultReplaceRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfileDefaultReplaceRequest.to_json())

# convert the object into a dict
workspace_runtime_profile_default_replace_request_dict = workspace_runtime_profile_default_replace_request_instance.to_dict()
# create an instance of WorkspaceRuntimeProfileDefaultReplaceRequest from a dict
workspace_runtime_profile_default_replace_request_from_dict = WorkspaceRuntimeProfileDefaultReplaceRequest.from_dict(workspace_runtime_profile_default_replace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


