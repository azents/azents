# WorkspaceRuntimeProfileDeleteResponse

Bounded impact from one committed Runtime Profile deletion.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**profile_id** | **str** |  | 
**cleared_workspace_default** | **bool** |  | 
**cleared_agent_count** | **int** |  | 
**affected_running_runtime_count** | **int** |  | 
**superseded_recreation_operation_count** | **int** |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_profile_delete_response import WorkspaceRuntimeProfileDeleteResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfileDeleteResponse from a JSON string
workspace_runtime_profile_delete_response_instance = WorkspaceRuntimeProfileDeleteResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfileDeleteResponse.to_json())

# convert the object into a dict
workspace_runtime_profile_delete_response_dict = workspace_runtime_profile_delete_response_instance.to_dict()
# create an instance of WorkspaceRuntimeProfileDeleteResponse from a dict
workspace_runtime_profile_delete_response_from_dict = WorkspaceRuntimeProfileDeleteResponse.from_dict(workspace_runtime_profile_delete_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


