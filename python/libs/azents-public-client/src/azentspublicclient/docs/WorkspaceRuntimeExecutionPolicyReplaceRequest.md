# WorkspaceRuntimeExecutionPolicyReplaceRequest

Complete optimistic Workspace policy replacement.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**restriction** | [**RuntimeExecutionPolicyRestriction**](RuntimeExecutionPolicyRestriction.md) |  | 
**allowed_profile_ids** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_execution_policy_replace_request import WorkspaceRuntimeExecutionPolicyReplaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeExecutionPolicyReplaceRequest from a JSON string
workspace_runtime_execution_policy_replace_request_instance = WorkspaceRuntimeExecutionPolicyReplaceRequest.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeExecutionPolicyReplaceRequest.to_json())

# convert the object into a dict
workspace_runtime_execution_policy_replace_request_dict = workspace_runtime_execution_policy_replace_request_instance.to_dict()
# create an instance of WorkspaceRuntimeExecutionPolicyReplaceRequest from a dict
workspace_runtime_execution_policy_replace_request_from_dict = WorkspaceRuntimeExecutionPolicyReplaceRequest.from_dict(workspace_runtime_execution_policy_replace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


