# WorkspaceRuntimeExecutionProfileResponse

Workspace availability of one Platform Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**lifecycle** | [**RuntimeExecutionProfileLifecycle**](RuntimeExecutionProfileLifecycle.md) |  | 
**version** | **int** |  | 
**policy** | [**RuntimeExecutionPolicyDocument**](RuntimeExecutionPolicyDocument.md) |  | 
**digest** | **str** |  | 
**reserved** | **bool** |  | 
**allowed** | **bool** |  | 
**available** | **bool** |  | 
**reason** | [**RuntimeExecutionAvailabilityReason**](RuntimeExecutionAvailabilityReason.md) |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_execution_profile_response import WorkspaceRuntimeExecutionProfileResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeExecutionProfileResponse from a JSON string
workspace_runtime_execution_profile_response_instance = WorkspaceRuntimeExecutionProfileResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeExecutionProfileResponse.to_json())

# convert the object into a dict
workspace_runtime_execution_profile_response_dict = workspace_runtime_execution_profile_response_instance.to_dict()
# create an instance of WorkspaceRuntimeExecutionProfileResponse from a dict
workspace_runtime_execution_profile_response_from_dict = WorkspaceRuntimeExecutionProfileResponse.from_dict(workspace_runtime_execution_profile_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


