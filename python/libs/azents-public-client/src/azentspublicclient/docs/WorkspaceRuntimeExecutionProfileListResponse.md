# WorkspaceRuntimeExecutionProfileListResponse

Workspace-visible Profile availability collection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[WorkspaceRuntimeExecutionProfileResponse]**](WorkspaceRuntimeExecutionProfileResponse.md) |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_execution_profile_list_response import WorkspaceRuntimeExecutionProfileListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeExecutionProfileListResponse from a JSON string
workspace_runtime_execution_profile_list_response_instance = WorkspaceRuntimeExecutionProfileListResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeExecutionProfileListResponse.to_json())

# convert the object into a dict
workspace_runtime_execution_profile_list_response_dict = workspace_runtime_execution_profile_list_response_instance.to_dict()
# create an instance of WorkspaceRuntimeExecutionProfileListResponse from a dict
workspace_runtime_execution_profile_list_response_from_dict = WorkspaceRuntimeExecutionProfileListResponse.from_dict(workspace_runtime_execution_profile_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


