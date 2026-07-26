# WorkspaceRuntimeExecutionPolicyResponse

Current explicit or implicit Workspace execution policy.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_id** | **str** |  | 
**version** | **int** |  | 
**restriction** | [**RuntimeExecutionPolicyRestriction**](RuntimeExecutionPolicyRestriction.md) |  | 
**digest** | **str** |  | 
**allowed_profile_ids** | **List[str]** |  | 
**updated_at** | **datetime** |  | 
**capabilities** | [**RuntimeExecutionManagementCapabilitiesResponse**](RuntimeExecutionManagementCapabilitiesResponse.md) |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_execution_policy_response import WorkspaceRuntimeExecutionPolicyResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeExecutionPolicyResponse from a JSON string
workspace_runtime_execution_policy_response_instance = WorkspaceRuntimeExecutionPolicyResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeExecutionPolicyResponse.to_json())

# convert the object into a dict
workspace_runtime_execution_policy_response_dict = workspace_runtime_execution_policy_response_instance.to_dict()
# create an instance of WorkspaceRuntimeExecutionPolicyResponse from a dict
workspace_runtime_execution_policy_response_from_dict = WorkspaceRuntimeExecutionPolicyResponse.from_dict(workspace_runtime_execution_policy_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


