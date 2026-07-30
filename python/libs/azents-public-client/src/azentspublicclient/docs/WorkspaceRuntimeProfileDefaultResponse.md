# WorkspaceRuntimeProfileDefaultResponse

Current optimistic Workspace Runtime Profile default.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**runtime_profile_id** | **str** |  | 
**version** | **int** |  | 
**profile** | [**WorkspaceRuntimeProfileResponse**](WorkspaceRuntimeProfileResponse.md) |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_profile_default_response import WorkspaceRuntimeProfileDefaultResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfileDefaultResponse from a JSON string
workspace_runtime_profile_default_response_instance = WorkspaceRuntimeProfileDefaultResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfileDefaultResponse.to_json())

# convert the object into a dict
workspace_runtime_profile_default_response_dict = workspace_runtime_profile_default_response_instance.to_dict()
# create an instance of WorkspaceRuntimeProfileDefaultResponse from a dict
workspace_runtime_profile_default_response_from_dict = WorkspaceRuntimeProfileDefaultResponse.from_dict(workspace_runtime_profile_default_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


