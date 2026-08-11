# WorkspaceRuntimeProfileDeleteRequest

Exact optimistic Workspace Runtime Profile deletion request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_profile_delete_request import WorkspaceRuntimeProfileDeleteRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfileDeleteRequest from a JSON string
workspace_runtime_profile_delete_request_instance = WorkspaceRuntimeProfileDeleteRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfileDeleteRequest.to_json())

# convert the object into a dict
workspace_runtime_profile_delete_request_dict = workspace_runtime_profile_delete_request_instance.to_dict()
# create an instance of WorkspaceRuntimeProfileDeleteRequest from a dict
workspace_runtime_profile_delete_request_from_dict = WorkspaceRuntimeProfileDeleteRequest.from_dict(workspace_runtime_profile_delete_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


